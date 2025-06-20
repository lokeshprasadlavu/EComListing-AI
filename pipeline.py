import os
import re
import json
import pandas as pd
import requests
import numpy as np
from io import BytesIO
from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageSequenceClip, AudioFileClip, concatenate_videoclips, concatenate_audioclips
import openai

# === ChatGPT Utilities ===

def get_chatgpt_response(prompt: str) -> str:
    resp = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=3000
    )
    return resp.choices[0].message['content'].strip()

def get_video_transcript(title: str, description: str) -> str:
    prompt = (
        f"You are the world’s best script writer for product videos under 1 minute. "
        f"Title: {title}\nDescription: {description}\n"
        "End the transcript with “Available on TrustClarity.com”."
    )
    return get_chatgpt_response(prompt)

# === Text Helpers ===

def clean_text(text: str) -> str:
    return text.encode('latin-1', 'replace').decode('latin-1')

def split_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list:
    lines = []
    words = text.split()
    current = ''
    while words:
        w = words.pop(0)
        test = current + w + ' '
        if font.getbbox(test)[2] <= max_width:
            current = test
        else:
            lines.append(current.strip())
            current = w + ' '
    if current:
        lines.append(current.strip())
    return lines

def split_text_into_slides(text: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int) -> list:
    slides, lines = [], split_text(text, font, max_width)
    for i in range(0, len(lines), max_lines):
        slides.append("\n".join(lines[i:i+max_lines]))
    return slides

# === Audio Helpers ===

def create_audio_with_gtts(text: str, output_path: str) -> str:
    def repl(m):
        txt = m.group(0)
        return txt.replace('-', ' dash ') if re.search(r"\d+-\d+", txt) else txt.replace('-', ' ')
    voice = re.sub(r"[A-Za-z0-9]+-[A-Za-z0-9]+", repl, text)
    tts = gTTS(text=voice, lang='en')
    tts.save(output_path)
    return output_path

# === Video Generation ===

def create_video_for_product(
    listing_id: str,
    product_id: str,
    title: str,
    description: str,
    images: list,
    output_folder: str,
    fonts_folder: str,
    audio_folder: str,
    logo: Image.Image,
    font: ImageFont.FreeTypeFont,
    title_font: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int
):
    transcript = clean_text(get_video_transcript(title, description))
    slides = split_text_into_slides(transcript, font, max_width, max_lines)
    if len(images) < len(slides):
        images *= ((len(slides)//len(images))+1)
    video_clips, audio_clips = [], []
    for idx, slide in enumerate(slides, start=1):
        data = images[idx-1]
        url = data.get('imageURL')
        resp = requests.get(url)
        img = Image.open(BytesIO(resp.content)).convert('RGB')
        ratio = min(640/img.width, 360/img.height)
        img = img.resize((int(img.width*ratio), int(img.height*ratio)), Image.LANCZOS)
        audio_path = os.path.join(audio_folder, f"{listing_id}_{product_id}_slide_{idx}.mp3")
        create_audio_with_gtts(slide, audio_path)
        aud = AudioFileClip(audio_path)
        canvas = Image.new('RGB',(1280,720),'white'); draw = ImageDraw.Draw(canvas)
        canvas.paste(logo,(20,20),logo)
        draw.text((50,200), title, font=title_font, fill='black')
        y = (720 - sum(font.getbbox(l)[3]+10 for l in slide.split('\n'))) // 2
        for line in slide.split('\n'):
            draw.text((50,y),line,font=font,fill='black')
            y+=font.getbbox(line)[3]+10
        canvas.paste(img,(1280-img.width-50,(720-img.height)//2))
        frame = np.array(canvas)
        clip = ImageSequenceClip([frame], durations=[aud.duration]).set_duration(aud.duration)
        video_clips.append(clip); audio_clips.append(aud)
    if video_clips:
        final = concatenate_videoclips(video_clips, method='compose').set_audio(concatenate_audioclips(audio_clips))
        final.write_videofile(os.path.join(output_folder, f"{listing_id}_{product_id}.mp4"), fps=24, audio_codec='aac')

# === Batch Pipeline ===

def create_videos_and_blogs_from_csv(input_csv: str, images_data: list, products_df: pd.DataFrame, output_base: str, **vk):
    df = pd.read_csv(input_csv)
    lookup = {(i['listingId'],i['productId']):i['images'] for i in images_data if i.get('images')}
    for _,r in df.iterrows():
        key=(r['listing_id'],r['product_id']); images=lookup.get(key)
        if not images: continue
        prod=products_df[(products_df['Listing Id']==key[0])&(products_df['Product Id']==key[1])]
        if prod.empty: continue
        title=f"{prod['Brand'].iat[0]} - {prod['MPN'].iat[0]}"; desc=prod['Description'].iat[0]
        folder=os.path.join(output_base,f"{key[0]}_{key[1]}"); os.makedirs(folder,exist_ok=True)
        create_video_for_product(str(key[0]),str(key[1]),title,desc,images,folder, **vk)
        prompt=f"Write a blog for product {title}: {desc}"
        blog=get_chatgpt_response(prompt)
        with open(os.path.join(folder,f"{key[0]}_{key[1]}.txt"),'w',encoding='utf-8') as f: f.write(blog)
        with open(os.path.join(folder,f"{key[0]}_{key[1]}_title.txt"),'w',encoding='utf-8') as f: f.write(title)

def upload_videos_streamlit(output_folder: str, upload_fn, embed_fn) -> list:
    results=[]
    for sub in os.listdir(output_folder):
        p=os.path.join(output_folder,sub)
        if not os.path.isdir(p): continue
        vid,blog,title = [os.path.join(p,f"{sub}{suf}") for suf in ['.mp4','.txt','_title.txt']]
        if not all(os.path.exists(x) for x in (vid,blog,title)):
            results.append((sub,False,"Missing files")); continue
        t=open(title).read().strip(); d=open(blog).read().strip()
        try:
            url=upload_fn(vid,t,d)
            upd=embed_fn(d,url)
            with open(blog,'w',encoding='utf-8') as f: f.write(upd)
            results.append((sub,True,url))
        except Exception as e:
            results.append((sub,False,str(e)))
    return results
