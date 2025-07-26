import logging
import os
import shutil
from dataclasses import dataclass
from typing import List, Optional

import openai
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    ImageClip,
    AudioFileClip,
    concatenate_videoclips,
    concatenate_audioclips,
)
from gtts import gTTS

from shared.utils import (
    download_images,
    slugify,
    get_persistent_cache_dir
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
    openai_api_key: str

@dataclass
class GenerationResult:
    video_path: str
    title_file: str
    blog_file: str

class GenerationError(Exception):
    pass

# ─── Video Generation ───
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
    
    os.environ["OPENAI_API_KEY"] = cfg.openai_api_key
    persistent_dir = get_persistent_cache_dir(base)
    audio_folder = os.path.join(persistent_dir, "audio")
    os.makedirs(audio_folder, exist_ok=True)
    workdir = os.path.join(persistent_dir, "workdir")
    os.makedirs(workdir, exist_ok=True)

    local_images = download_images(image_urls, workdir)
    if not local_images:
        log.error(f"No images downloaded for {base}. URLs: {image_urls}")
        raise GenerationError("❌ No images downloaded – check your URLs.")

    transcript = generate_transcript(title, description)
    if not transcript:
        log.error(f"Transcript generation failed for {base}. Empty transcript.")
        raise GenerationError("❌ Generation failed.")
    

    font_path = os.path.join(cfg.fonts_zip_path, "Poppins-Light.ttf")
    bold_font_path = os.path.join(cfg.fonts_zip_path, "Poppins-Bold.ttf")
    if not os.path.exists(font_path) or not os.path.exists(bold_font_path):
        raise GenerationError("Font not found.")

    try:
        font = ImageFont.truetype(font_path, 35)
        bold_font = ImageFont.truetype(bold_font_path, 38)
    except Exception as e:
        log.exception("Failed to load fonts")
        raise GenerationError(f"Failed to load font: {e}")

    slides = split_text_into_slides(transcript, font, 600, 3)
    if len(slides) > len(local_images):
        local_images *= (len(slides) // len(local_images)) + 1

    logo_img = None
    if os.path.exists(cfg.logo_path):
        logo_img = Image.open(cfg.logo_path).convert("RGBA").resize((150, 80))

    clips = []
    audio_clips = []
    for i, slide_text in enumerate(slides):
        img = Image.open(local_images[i]).convert("RGB")
        img.thumbnail((640, 360), Image.LANCZOS)

        canvas = Image.new("RGB", (1280, 720), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)

        # Logo top-left
        if logo_img:
            canvas.paste(logo_img, (20, 20), logo_img)

        # Title text
        draw.text((50, 200), title, font=bold_font, fill="black")

        # Slide text
        lines = slide_text.split('\n')
        text_y = (720 - sum(font.getbbox(line)[3] + 10 for line in lines)) // 2
        for line in lines:
            draw.text((50, text_y), line, font=font, fill="black")
            text_y += font.getbbox(line)[3] + 10

        # Paste image on right
        canvas.paste(img, (1280 - img.width - 50, (720 - img.height) // 2))

        frame_path = os.path.join(workdir, f"frame_{i}.jpg")
        canvas.save(frame_path)

        audio_path = os.path.join(audio_folder, f"{base}_slide_{i + 1}.mp3")
        create_audio_with_gtts(slide_text, audio_path)
        audio_clip = AudioFileClip(audio_path)

        frame_clip = ImageClip(frame_path).set_duration(audio_clip.duration)
        clips.append(frame_clip)
        audio_clips.append(audio_clip)

    final_video = concatenate_videoclips(clips, method="compose")
    final_audio = concatenate_audioclips(audio_clips)
    final_output = final_video.set_audio(final_audio)

    output_path = os.path.join(workdir, f"{base}.mp4")
    final_output.write_videofile(output_path, codec="libx264", audio_codec="aac", fps=24)

    blog_file = os.path.join(workdir, f"{base}_blog.txt")
    title_file = os.path.join(workdir, f"{base}_title.txt")
    with open(blog_file, "w", encoding="utf-8") as bf:
        bf.write(transcript)
    with open(title_file, "w", encoding="utf-8") as tf:
        tf.write(title)

    persist_output = os.path.join(cfg.output_base_folder, base)
    os.makedirs(persist_output, exist_ok=True)
    shutil.copy(output_path, os.path.join(persist_output, os.path.basename(output_path)))
    shutil.copy(blog_file, os.path.join(persist_output, os.path.basename(blog_file)))
    shutil.copy(title_file, os.path.join(persist_output, os.path.basename(title_file)))

    return GenerationResult(
        video_path=os.path.join(persist_output, os.path.basename(output_path)),
        title_file=os.path.join(persist_output, os.path.basename(title_file)),
        blog_file=os.path.join(persist_output, os.path.basename(blog_file))
    )


# ─── Helpers ───
def generate_transcript(title: str, description: str) -> str:
    prompt = (
        f"You are the world’s best script writer for product videos. "
        f"Write a voiceover script in **130 to 140 words** for:\nTitle: {title}\nDescription: {description}\n"
        "End with 'Available on Our Website.'"
        f"Do not format as a video script or include voiceover-style text. Write as a typical blog article."
    )
    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=500
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        log.exception(f"Transcript generation failed: {e}")
        raise GenerationError(f"⚠️ Transcript generation failed: {e}")


def split_text_into_slides(text, font, max_width, max_lines):
    slides = []
    words = text.split()
    current_slide_lines = []
    current_line = ''
    while words:
        word = words.pop(0)
        potential_line = current_line + word + ' '
        if font.getbbox(potential_line)[2] <= max_width:
            current_line = potential_line
        else:
            current_slide_lines.append(current_line.strip())
            current_line = word + ' '
            if len(current_slide_lines) >= max_lines:
                slides.append('\n'.join(current_slide_lines))
                current_slide_lines = []
    if current_line:
        current_slide_lines.append(current_line.strip())
    if current_slide_lines:
        slides.append('\n'.join(current_slide_lines))
    return slides


def create_audio_with_gtts(text, output_path):
    try:
        tts = gTTS(text=text, lang='en')
        tts.save(output_path)
    except Exception as e:
        log.exception(f"GTTS audio generation failed: {e}")
        raise GenerationError(f"⚠️ Failed to generate audio: {e}")
