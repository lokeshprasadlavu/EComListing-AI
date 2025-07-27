import logging
import os
import io
import shutil
import tempfile
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
    load_fonts_from_drive,
    load_logo_from_drive,
    upload_output_files_to_drive,
)

# ─── Logger Setup ───
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ─── Data Classes ───
@dataclass
class ServiceConfig:
    drive_service: any
    drive_folder_id: str
    fonts_folder_id: str
    logo_folder_id: str
    output_folder_id: str
    openai_api_key: str

@dataclass
class GenerationResult:
    folder: str
    video: str
    blog: str
    title: str

class GenerationError(Exception):
    pass

# ─── Video Generation ───
def generate_video(
    cfg: ServiceConfig,
    listing_id: Optional[str],
    product_id: Optional[str],
    title: str,
    description: str,
    image_urls: Optional[List[str]] = None,
    image_files: Optional[List[bytes]] = None
) -> GenerationResult:
    base = f"{listing_id}_{product_id}" if listing_id and product_id and listing_id != product_id else slugify(title)
    log.info(f"🎬 Generating content for: {base}")
    
    os.environ["OPENAI_API_KEY"] = cfg.openai_api_key
    with tempfile.TemporaryDirectory() as tmpdir:
        fonts = load_fonts_from_drive(cfg.fonts_folder_id)
        logo = load_logo_from_drive(cfg.logo_folder_id)

        try:
            font = ImageFont.truetype(io.BytesIO(fonts["Poppins-Light.ttf"]), 35)
            bold_font = ImageFont.truetype(io.BytesIO(fonts["Poppins-Bold.ttf"]), 38)
        except Exception as e:
            raise GenerationError(f"❌ Failed to load fonts: {e}")

        logo_img = Image.open(io.BytesIO(logo)).convert("RGBA").resize((150, 80))

        if image_files:
            local_images = image_files
        elif image_urls:
            local_images = [b for _, b in download_images(image_urls)]
        else:
            raise GenerationError("No image input provided.")

        if not local_images:
            raise GenerationError("❌ No images available to generate video.")

        transcript = generate_transcript(title, description)
        if not transcript:
            log.error(f"Transcript generation failed for {base}. Empty transcript.")
            raise GenerationError("❌ Generation failed.")

        slides = split_text_into_slides(transcript, font, 600, 3)
        if len(slides) > len(local_images):
            local_images *= (len(slides) // len(local_images)) + 1

        clips = []
        audio_clips = []
        for i, slide_text in enumerate(slides):
            img = Image.open(io.BytesIO(local_images[i])).convert("RGB")
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

            frame_path = f"{tmpdir}/frame_{i}.jpg"
            canvas.save(frame_path)

            audio_path = f"{tmpdir}/{base}_slide_{i + 1}.mp3"
            create_audio_with_gtts(slide_text, audio_path)
            audio_clip = AudioFileClip(audio_path)

            frame_clip = ImageClip(frame_path).set_duration(audio_clip.duration)
            clips.append(frame_clip)
            audio_clips.append(audio_clip)

        final_video = concatenate_videoclips(clips, method="compose")
        final_audio = concatenate_audioclips(audio_clips)
        final_output = final_video.set_audio(final_audio)

        video_filename = f"{base}.mp4"
        blog_filename = f"{base}_blog.txt"
        title_filename = f"{base}_title.txt"

        video_path = f"{tmpdir}/{video_filename}"
        blog_path = f"{tmpdir}/{blog_filename}"
        title_path = f"{tmpdir}/{title_filename}"

        final_output.write_videofile(video_path, codec="libx264", audio_codec="aac", fps=24)

        with open(blog_path, "w", encoding="utf-8") as bf:
            bf.write(transcript)
        with open(title_path, "w", encoding="utf-8") as tf:
            tf.write(title)

        file_map = {
            video_filename: open(video_path, "rb").read(),
            blog_filename: open(blog_path, "rb").read(),
            title_filename: open(title_path, "rb").read(),
        }

        upload_output_files_to_drive(file_map, parent_folder=cfg.output_folder_id, base_name=base)

        return GenerationResult(
            folder=f"{base}",
            video=video_filename,
            blog=blog_filename,
            title=title_filename
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
