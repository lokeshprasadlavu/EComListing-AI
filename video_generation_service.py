import logging
import os
import shutil
from dataclasses import dataclass
from typing import List, Optional

import openai
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    ImageClip,
    CompositeVideoClip,
    AudioFileClip,
    concatenate_videoclips,
)
from gtts import gTTS

from utils import (
    download_images,
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
def generate_video(
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

    local_images = download_images(image_urls, workdir)
    if not local_images:
        raise GenerationError("❌ No images downloaded – check your URLs.")

    transcript = generate_transcript(title, description)
    if not transcript:
        raise GenerationError("❌ Transcript generation failed.")

    try:
        tts = gTTS(text=transcript, lang="en")
        audio_path = os.path.join(audio_folder, f"{base}_narration.mp3")
        tts.save(audio_path)
    except Exception as e:
        raise GenerationError(f"❌ Voiceover generation failed: {e}")

    audio_clip = AudioFileClip(audio_path)

    logo_path = cfg.logo_path if os.path.exists(cfg.logo_path) else None
    font_path = os.path.join(cfg.fonts_zip_path, "Poppins-Bold.ttf")
    if not os.path.exists(font_path):
        raise GenerationError(f"Font not found: {font_path}")

    # Prepare composite frames
    clips = []
    for idx, image_path in enumerate(local_images):
        frame = compose_frame(
            image_path=image_path,
            text=transcript,
            logo_path=logo_path,
            font_path=font_path,
            size=(1280, 720),
            duration=audio_clip.duration / len(local_images)
        )
        clips.append(frame)

    final_clip = concatenate_videoclips(clips).set_audio(audio_clip)

    output_path = os.path.join(workdir, f"{base}.mp4")
    final_clip.write_videofile(output_path, codec="libx264", audio_codec="aac", fps=24)

    blog_file = os.path.join(workdir, f"{base}_blog.txt")
    title_file = os.path.join(workdir, f"{base}_title.txt")
    with open(blog_file, "w", encoding="utf-8") as bf:
        bf.write(transcript)
    with open(title_file, "w", encoding="utf-8") as tf:
        tf.write(title)

    persist_output = os.path.join(cfg.output_base_folder, base)
    os.makedirs(persist_output, exist_ok=True)

    final_video = os.path.join(persist_output, os.path.basename(output_path))
    final_blog = os.path.join(persist_output, os.path.basename(blog_file))
    final_title = os.path.join(persist_output, os.path.basename(title_file))

    shutil.copy(output_path, final_video)
    shutil.copy(blog_file, final_blog)
    shutil.copy(title_file, final_title)

    return GenerationResult(final_video, final_title, final_blog)

# ─── Frame Composer ───
def compose_frame(image_path, text, logo_path, font_path, size=(1280, 720), duration=2):
    img = Image.open(image_path).convert("RGB")
    img = img.resize((size[0] // 2, size[1]))

    bg = Image.new("RGB", size, "white")
    bg.paste(img, (0, 0))

    draw = ImageDraw.Draw(bg)
    font = ImageFont.truetype(font_path, 28)
    wrapped_text = wrap_text(text, font, size[0] // 2 - 40)
    draw.multiline_text((size[0] // 2 + 20, 100), wrapped_text, font=font, fill="black")

    if logo_path:
        logo = Image.open(logo_path).convert("RGBA").resize((150, 80))
        bg.paste(logo, (size[0] // 2 + 20, 10), mask=logo)

    frame_path = image_path.replace(".jpg", "_frame.jpg")
    bg.save(frame_path)

    return ImageClip(frame_path).set_duration(duration)

# ─── Transcript Generation ───
def generate_transcript(title: str, description: str) -> str:
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

# ─── Text Wrapper ───
def wrap_text(text, font, max_width):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test_line = f"{current} {word}".strip()
        if font.getlength(test_line) <= max_width:
            current = test_line
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return "\n".join(lines)
