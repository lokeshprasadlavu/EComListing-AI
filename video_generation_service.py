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
    for img in local_images:
        if not os.path.exists(img):
            raise GenerationError(f"❌ Image file missing: {img}")
    for img in local_images:
        if os.path.getsize(img) == 0:
            raise GenerationError(f"❌ Image file corrupted (0 bytes): {img}")

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

# ─── Transcript Generation ───
def _generate_transcript(title: str, description: str) -> str:
    prompt = (
        f"You are the world’s best script writer for product videos. "
        f"Write a one-minute voiceover script for:\nTitle: {title}\nDescription: {description}\n"
        "End with 'Available on Our Website.'"
        f"Do not format as a video script or include voiceover-style text. Write as a typical blog article."
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
    # Generate narration
    try:
        tts = gTTS(text=narration_text, lang="en")
        audio_path = os.path.join(audio_folder, f"{basename}_narration.mp3")
        tts.save(audio_path)
    except Exception as e:
        raise GenerationError(f"❌ Voiceover generation failed: {e}")

    # Create audio clip 
    if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1024:
        raise GenerationError("❌ Audio file corrupted or not saved properly.")
    audio_clip = AudioFileClip(audio_path)

    if not images:
        raise GenerationError("❌ No valid images provided for video generation.")

    for img_path in images:
        if not os.path.exists(img_path):
            raise GenerationError(f"❌ Missing image file: {img_path}")

    # Create image clip
    resized_images = []
    base_width, base_height = Image.open(images[0]).size

    for idx, path in enumerate(images):
        img = Image.open(path).convert("RGB")
        resized = img.resize((base_width, base_height), resample=Image.LANCZOS)
        resized_path = os.path.join(workdir, f"resized_{idx}.jpg")
        resized.save(resized_path)
        resized_images.append(resized_path)

    clip = ImageSequenceClip(resized_images, fps=1).set_audio(audio_clip)

    # Create PIL text overlay as ImageClip
    font_path = os.path.join(fonts_folder, "Poppins-Bold.ttf")
    if not os.path.exists(font_path):
        raise GenerationError(f"Font not found: {font_path}")

    try:
        # Create transparent image for text
        txt_img = Image.new("RGBA", (clip.w, 100), (0, 0, 0, 0))
        draw = ImageDraw.Draw(txt_img)
        font = ImageFont.truetype(font_path, 30)

        # Centered title
        bbox = draw.textbbox((0, 0), title_text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        position = ((clip.w - text_width) // 2, (100 - text_height) // 2)
        draw.text(position, title_text, font=font, fill=(255, 255, 255, 255))

        # Save text image
        txt_path = os.path.join(workdir, f"{basename}_text.png")
        txt_img.save(txt_path)

        # Convert to ImageClip
        txt_clip = ImageClip(txt_path).set_duration(clip.duration)
    except Exception as e:
        raise GenerationError(f"❌ Title overlay creation failed: {e}")

    # Combine layers
    layers = [clip, txt_clip]
    if logo_clip:
        layers.append(logo_clip.set_duration(clip.duration))

    final = CompositeVideoClip(layers)

    # Export video
    out_path = os.path.join(workdir, f"{basename}.mp4")
    try:
        final.write_videofile(out_path, codec="libx264", audio_codec="aac")
    except Exception as e:
        raise GenerationError(f"❌ Video rendering failed: {e}")
    finally:
        # Always release resources
        final.close()
        audio_clip.close()
        clip.close()
        if logo_clip:
            logo_clip.close()
        if 'txt_clip' in locals():
            txt_clip.close()

    return out_path
