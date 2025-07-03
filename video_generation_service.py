import logging
import os
import re
import shutil
from dataclasses import dataclass
from typing import List, Dict, Optional

import pandas as pd
import openai
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    ImageSequenceClip,
    AudioFileClip,
    ImageClip,
    CompositeVideoClip,
)
from gtts import gTTS

from utils import (
    download_images
    ,
    slugify,
    validate_images_json,
    get_persistent_cache_dir,
)

# ─── Logger Setup ───
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ─── Data Classes ───
@dataclass
class ServiceConfig:
    csv_file: str
    images_json: str
    audio_folder: str
    fonts_zip_path: str
    logo_path: str
    output_base_folder: str

@dataclass
class GenerationResult:
    video_path: str
    title_file: str
    blog_file: str

class GenerationError(Exception):
    pass

# ─── Single Product Generation ───
def generate_for_single(
    cfg: ServiceConfig,
    listing_id: Optional[str],
    product_id: Optional[str],
    title: str,
    description: str,
    image_urls: List[str],
) -> GenerationResult:
    base = f"{listing_id}_{product_id}" if listing_id and product_id and listing_id != product_id else slugify(title)
    log.info(f"🎬 Generating content for: {base}")

    persistent_dir = get_persistent_cache_dir(base)
    audio_folder = os.path.join(persistent_dir, "audio")
    os.makedirs(audio_folder, exist_ok=True)
    workdir = os.path.join(persistent_dir, "workdir")
    os.makedirs(workdir, exist_ok=True)

    # Download images
    local_images = download_images(image_urls, workdir)
    if not local_images:
        raise GenerationError("❌ No images downloaded – check your URLs.")

    # Logo
    logo_clip = None
    if cfg.logo_path and os.path.isfile(cfg.logo_path):
        try:
            logo_image = Image.open(cfg.logo_path).convert("RGBA")
            resized_logo = logo_image.resize((150, 80), resample=Image.LANCZOS)
            resized_path = os.path.join(persistent_dir, "resized_logo.png")
            resized_logo.save(resized_path)
            logo_clip = ImageClip(resized_path).set_duration(1).set_pos((10, 10))
        except Exception as e:
            log.warning(f"⚠️ Failed to process logo: {e}")

    # Transcript
    transcript = _generate_transcript(title, description)
    if not transcript:
        raise GenerationError("❌ Transcript generation failed.")

    # Assemble video
    video_path = _assemble_video(
        images=local_images,
        narration_text=transcript,
        logo_clip=logo_clip,
        title_text=title,
        fonts_folder=cfg.fonts_zip_path,
        audio_folder=audio_folder,
        workdir=workdir,
        basename=base,
    )

    # Write blog + title files
    blog_file = os.path.join(workdir, f"{base}_blog.txt")
    title_file = os.path.join(workdir, f"{base}_title.txt")
    with open(blog_file, "w", encoding="utf-8") as bf:
        bf.write(transcript)
    with open(title_file, "w", encoding="utf-8") as tf:
        tf.write(title)

    log.info(f"✅ Completed: {base}")
    # Save files to persistent output folder before returning
    persist_output = os.path.join(cfg.output_base_folder, base)
    os.makedirs(persist_output, exist_ok=True)

    final_video = os.path.join(persist_output, os.path.basename(video_path))
    final_blog = os.path.join(persist_output, os.path.basename(blog_file))
    final_title = os.path.join(persist_output, os.path.basename(title_file))

    shutil.copy(video_path, final_video)
    shutil.copy(blog_file, final_blog)
    shutil.copy(title_file, final_title)

    return GenerationResult(final_video, final_title, final_blog)

# ─── Batch CSV Generation ───
def generate_batch_from_csv(
    cfg: ServiceConfig,
    images_data: Optional[List[Dict]] = None,
) -> None:
    if not os.path.exists(cfg.csv_file):
        raise GenerationError(f"CSV not found: {cfg.csv_file}")

    df = pd.read_csv(cfg.csv_file)
    df.columns = [c.strip() for c in df.columns]

    required = ['Listing Id', 'Product Id', 'Title', 'Description']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise GenerationError(f"❌ Missing columns in CSV: {', '.join(missing)}")

    url_col = next((c for c in df.columns if 'image' in c.lower() and 'url' in c.lower()), None)
    image_map = {}

    if images_data:
        try:
            validate_images_json(images_data)
            for entry in images_data:
                key = (entry['listingId'], entry['productId'])
                urls = [img['imageURL'] for img in entry['images']]
                image_map[key] = urls
        except Exception as e:
            raise GenerationError(f"❌ Invalid images JSON: {e}")

    for _, row in df.iterrows():
        lid, pid = str(row['Listing Id']), str(row['Product Id'])
        title, desc = str(row['Title']), str(row['Description'])
        key = (int(lid), int(pid)) if all(i.isdigit() for i in [lid, pid]) else (lid, pid)

        urls = image_map.get(key, [])
        if not urls and url_col:
            raw = str(row[url_col] or "")
            urls = [u.strip() for u in raw.split(',') if re.search(r'\.(png|jpe?g)(\?|$)', u, re.IGNORECASE)]

        if not urls:
            log.warning(f"⚠️ Skipping {lid}/{pid} – No valid image URLs")
            continue
        if not title or not desc:
            log.warning(f"⚠️ Skipping {lid}/{pid} – Missing title or description")
            continue

        result = generate_for_single(
            cfg=cfg,
            listing_id=lid,
            product_id=pid,
            title=title,
            description=desc,
            image_urls=urls,
        )

        # Save result files
        dest = os.path.join(cfg.output_base_folder, f"{lid}_{pid}")
        os.makedirs(dest, exist_ok=True)
        for f in [result.video_path, result.blog_file, result.title_file]:
            shutil.copy(f, os.path.join(dest, os.path.basename(f)))
        log.info(f"📁 Saved: {lid}/{pid} to {dest}")

# ─── Transcript Generation ───
def _generate_transcript(title: str, description: str) -> str:
    prompt = (
        f"You are the world’s best script writer for product videos. "
        f"Write a one-minute voiceover script for:\nTitle: {title}\nDescription: {description}\n"
        "End with 'Available on Our Website.'"
    )
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=500
        )
        return response.choices[0].message.content.strip()
    except openai.error.OpenAIError as e:
        raise GenerationError(f"❌ OpenAI error: {e}")
    except Exception:
        raise GenerationError("⚠️ Unexpected error generating transcript.")

# ─── Video Assembly ───
def _assemble_video(
    images: List[str],
    narration_text: str,
    logo_clip: Optional[ImageClip],
    title_text: str,
    fonts_folder: str,
    audio_folder: str,
    workdir: str,
    basename: str,
) -> str:
    # Generate audio
    try:
        tts = gTTS(text=narration_text, lang="en")
        audio_path = os.path.join(audio_folder, f"{basename}_narration.mp3")
        tts.save(audio_path)
    except Exception as e:
        raise GenerationError(f"❌ Voiceover generation failed: {e}")

    audio_clip = AudioFileClip(audio_path)
    clip = ImageSequenceClip(images, fps=1).set_audio(audio_clip)

    # Create title overlay
    font_path = os.path.join(fonts_folder, "Poppins-Bold.ttf")
    if not os.path.exists(font_path):
        raise GenerationError(f"Font not found: {font_path}")

    try:
        txt_img = Image.new("RGBA", (clip.w, 100), (0, 0, 0, 0))
        draw = ImageDraw.Draw(txt_img)
        font = ImageFont.truetype(font_path, 30)
        text_width, _ = draw.textsize(title_text, font=font)
        draw.text(((clip.w - text_width) // 2, 10), title_text, font=font, fill=(255, 255, 255, 255))
        txt_path = os.path.join(workdir, f"{basename}_text.png")
        txt_img.save(txt_path)
        txt_clip = ImageClip(txt_path).set_duration(clip.duration)
    except Exception as e:
        raise GenerationError(f"❌ Title overlay creation failed: {e}")

    layers = [clip, txt_clip]
    if logo_clip:
        layers.append(logo_clip.set_duration(clip.duration))

    final = CompositeVideoClip(layers)
    out_path = os.path.join(workdir, f"{basename}.mp4")

    try:
        final.write_videofile(out_path, codec="libx264", audio_codec="aac")
    except Exception as e:
        raise GenerationError(f"❌ Video rendering failed: {e}")

    return out_path
