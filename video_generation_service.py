import logging
import os
import shutil
from dataclasses import dataclass
from typing import List, Dict, Optional

import pandas as pd
import openai
from PIL import Image
from moviepy.editor import (
    ImageSequenceClip,
    AudioFileClip,
    concatenate_videoclips,
    concatenate_audioclips,
    TextClip,
    ImageClip,
    CompositeVideoClip,
)
from gtts import gTTS

from io_utils import download_images, temp_workspace, slugify

# Configure module-level logger
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


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


def generate_for_single(
    cfg: ServiceConfig,
    listing_id: Optional[str],
    product_id: Optional[str],
    title: str,
    description: str,
    image_urls: List[str],
) -> GenerationResult:
    """
    Generate video + blog + title for a single product.
    If listing_id/product_id are missing, use slug of title.
    """
    # Determine output base name
    if not listing_id or not product_id:
        base = slugify(title)
    else:
        base = f"{listing_id}_{product_id}" if listing_id != product_id else listing_id
    log.info(f"Starting generation for {base}")

    with temp_workspace() as workdir:
        # Download images locally
        log.debug("Downloading images for single product")
        local_images = download_images(image_urls, workdir)

        # map fonts directory
        fonts_dir = cfg.fonts_zip_path

        # Prepare logo clip
        logo_clip = None
        try:
            img_logo = Image.open(cfg.logo_path).convert("RGBA")
            logo_clip = ImageClip(cfg.logo_path).set_duration(1)
            logo_clip = logo_clip.resize(height=80).set_pos((10, 10))
        except Exception:
            log.warning("Unable to load logo at %s", cfg.logo_path)

        # Generate transcript
        transcript = _generate_transcript(title, description)
        if not transcript:
            log.error("Transcript generation failed, aborting.")
            raise RuntimeError("Transcript generation failed")

        # Assemble video
        video_path = _assemble_video(
            images=local_images,
            narration_text=transcript,
            logo_clip=logo_clip,
            title_text=title,
            fonts_folder=fonts_dir,
            audio_folder=cfg.audio_folder,
            workdir=workdir,
            basename=base,
        )

        # Write blog & title files
        blog_file = os.path.join(workdir, f"{base}_blog.txt")
        title_file = os.path.join(workdir, f"{base}_title.txt")
        with open(blog_file, "w", encoding="utf-8") as bf:
            bf.write(transcript)
        with open(title_file, "w", encoding="utf-8") as tf:
            tf.write(title)

        log.info(f"Completed generation for {base}")
        return GenerationResult(video_path, title_file, blog_file)


def generate_batch_from_csv(
    cfg: ServiceConfig,
    images_data: List[Dict],
) -> None:
    """
    Process a batch by reading cfg.csv_file and cfg.images_json.
    Calls generate_for_single for each entry, organizes outputs.
    """
    df = pd.read_csv(cfg.csv_file)
    df.columns = [c.strip() for c in df.columns]
    # build image lookup
    image_map = {
        (e['listingId'], e['productId']): [img['imageURL'] for img in e.get('images', [])]
        for e in images_data
        if e.get('listingId') and e.get('productId')
    }

    for _, row in df.iterrows():
        lid = row.get('Listing Id')
        pid = row.get('Product Id')
        title = row.get('Title', '')
        desc = row.get('Description', '')
        key = (lid, pid)

        if key not in image_map:
            log.warning(f"Skipping {lid}/{pid}: no images")
            continue
        if not title or not desc:
            log.warning(f"Skipping {lid}/{pid}: missing title/description")
            continue

        # create per-product workspace
        with temp_workspace() as tmp:
            svc_cfg = ServiceConfig(
                csv_file=cfg.csv_file,
                images_json=cfg.images_json,
                audio_folder=tmp,
                fonts_zip_path=cfg.fonts_zip_path,
                logo_path=cfg.logo_path,
                output_base_folder=cfg.output_base_folder,
            )
            # generate single
            result = generate_for_single(
                cfg=svc_cfg,
                listing_id=str(lid),
                product_id=str(pid),
                title=str(title),
                description=str(desc),
                image_urls=image_map[key],
            )
            # move outputs to final folder
            dest = os.path.join(cfg.output_base_folder, f"{lid}_{pid}")
            os.makedirs(dest, exist_ok=True)
            shutil.copy(result.video_path, os.path.join(dest, os.path.basename(result.video_path)))
            shutil.copy(result.blog_file,  os.path.join(dest, os.path.basename(result.blog_file)))
            shutil.copy(result.title_file, os.path.join(dest, os.path.basename(result.title_file)))
            log.info(f"Saved outputs for {lid}/{pid} to {dest}")


def _generate_transcript(title: str, description: str) -> str:
    prompt = (
        f"You are the world’s best script writer for product videos. "
        f"Write a one-minute voiceover script for:\nTitle: {title}\nDescription: {description}\n"
        "End with 'Available on TrustClarity.com.'"
    )
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=500
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        log.exception("OpenAI transcript generation failed")
        return ""


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
    # create narration audio
    tts = gTTS(text=narration_text, lang="en")
    audio_path = os.path.join(audio_folder, f"{basename}_narration.mp3")
    tts.save(audio_path)
    audio_clip = AudioFileClip(audio_path)

    # create image sequence clip
    clip = ImageSequenceClip(images, fps=1).set_audio(audio_clip)

    # title overlay
    font_path = os.path.join(fonts_folder, "Poppins-Bold.ttf")
    txt_clip = (TextClip(title_text, fontsize=30, font=font_path,
                         color="white", method="caption",
                         size=(int(clip.w*0.8), None))
                .set_position((50,50)).set_duration(clip.duration))

    # compose all
    layers = [clip, txt_clip]
    if logo_clip:
        layers.append(logo_clip.set_duration(clip.duration))
    final = CompositeVideoClip(layers)

    # write file
    out_path = os.path.join(workdir, f"{basename}.mp4")
    final.write_videofile(out_path, codec="libx264", audio_codec="aac")
    return out_path