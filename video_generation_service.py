import os
import re
import json
import pandas as pd
import requests
import numpy as np
from io import BytesIO
from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont
import zipfile
import shutil
from moviepy.editor import ImageSequenceClip, AudioFileClip, concatenate_videoclips, concatenate_audioclips
import openai


# Placeholders for paths (to be injected at runtime by app.py)
csv_file       = None
output_folder  = None
audio_folder   = None
fonts_folder   = None
poppins_zip    = None
logo_path      = None
images_json    = None
logo          = None


# === ChatGPT Utilities ===

def get_chatgpt_response(prompt):
    """
    Function to send a prompt to ChatGPT and retrieve the response.

    Parameters:
    - prompt: str, the prompt to send to ChatGPT.

    Returns:
    - The response content from ChatGPT as a string.
    """
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",  # or "gpt-4" if available
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000
        )
        return response.choices[0].message['content'].strip()
    except Exception as e:
        return f"Error: {str(e)}"
    raise

def get_video_transcript(title, description):
    """
    Generates a video transcript using ChatGPT and preprocesses it for better TTS pronunciation.

    Parameters:
    - title (str): The title of the product.
    - description (str): The product description.

    Returns:
    - str: The preprocessed transcript suitable for voiceover.
    """
    prompt = f"""You are the world’s best script writer for product videos. The transcript you write will be used in videos as voiceovers, the video will run under 1 minute. Here is the product title: "{title}", description: "{description}". End the transcript with “Available on TrustClarity.com"."""

    return get_chatgpt_response(prompt)

# === Text Refinement ===

def clean_text(text: str) -> str:
    return text.encode('latin-1', 'replace').decode('latin-1')

def split_text_into_slides(text, font, max_width, max_lines):
    slides = []
    words = text.split()
    current_slide_lines = []
    current_line = ''
    while words:
        word = words.pop(0)
        potential_line = current_line + word + ' '
        # Compare the width of the potential line
        if font.getbbox(potential_line)[2] <= max_width:
            current_line = potential_line
        else:
            # Line is full, add to current slide
            current_slide_lines.append(current_line.strip())
            current_line = word + ' '
            # Check if current slide has reached max_lines
            if len(current_slide_lines) >= max_lines:
                # Slide is full, add to slides
                slides.append('\n'.join(current_slide_lines))
                current_slide_lines = []
    # Add any remaining text to slides
    if current_line:
        current_slide_lines.append(current_line.strip())
    if current_slide_lines:
        slides.append('\n'.join(current_slide_lines))
    return slides
    
def split_text(text, font, max_width):
    lines = []
    words = text.split()
    current_line = ''
    while words:
        word = words.pop(0)
        potential_line = current_line + word + ' '
        # Corrected to compare the width
        if font.getbbox(potential_line)[2] <= max_width:
            current_line = potential_line
        else:
            lines.append(current_line.strip())
            current_line = word + ' '
    if current_line:
        lines.append(current_line.strip())
    return lines

# === Audio Generation ===

def create_audio_with_gtts(text, output_path):
    """
    Function to generate text-to-speech audio using Google TTS, with selective hyphen replacement.
    Hyphens in product codes (alphanumeric with hyphens) are replaced with "dash",
    while hyphens in compound words are replaced with a space.

    Parameters:
    - text (str): The text to convert to speech.
    - output_path (str): Path to save the generated audio file.

    Returns:
    - Path to the saved audio file.
    """

    # Replace hyphens in product codes with " dash "
    def replace_hyphen(match):
        matched_text = match.group(0)
        if re.search(r"\d+-\d+", matched_text):  # Check if it's a product code format (e.g., numbers with hyphens)
            return matched_text.replace("-", " dash ")
        else:
            return matched_text.replace("-", " ")

    # Apply replacement to the text
    voiceover_text = re.sub(r"[A-Za-z0-9]+-[A-Za-z0-9]+", replace_hyphen, text)

    try:
        tts = gTTS(text=voiceover_text, lang='en')
        tts.save(output_path)
        return output_path
    except Exception as e:
        print(f"Error generating audio with Google TTS: {e}")
        return None

# === Video Generation ===

def create_video_for_product(listing_id, product_id, title, text, images, output_folder):
    video_clips = []
    audio_clips = []

    # Generate a more conversational transcript using ChatGPT
    transcript_text = get_video_transcript(title, text)

    # Clean the transcript to avoid encoding issues
    transcript_text = clean_text(transcript_text)

    # Split transcript into slides
    font_path = os.path.join(fonts_folder, 'Poppins-Light.ttf')
    font_size = 35
    try:
        font = ImageFont.truetype(font_path, font_size)
    except OSError:
        print("Roboto font could not be loaded. Check the font path.")
        return


    # Load the bold version of the font
    title_font_path = os.path.join(fonts_folder, 'Poppins-Bold.ttf')

    slides_text = split_text_into_slides(transcript_text, font, 600, 3)  # Adjust max_width and max_lines as needed

    # Ensure there are images for each slide
    images = images if len(images) >= len(slides_text) else images * ((len(slides_text) // len(images)) + 1)

    # Creating video clips for each slide
    for i, slide_text in enumerate(slides_text):
        img_data = images[i % len(images)]
        img_url = img_data.get('imageURL')
        if not img_url:
            print(f"Image URL missing for slide {i+1}")
            continue

        # Download image
        response = requests.get(img_url)
        if response.status_code != 200:
            print(f"Failed to download image from URL: {img_url}")
            continue
        img = Image.open(BytesIO(response.content)).convert('RGB')

        # Resize image
        max_img_width, max_img_height = 640, 360
        img_aspect_ratio = img.width / img.height
        if img.width / max_img_width > img.height / max_img_height:
            new_width = min(img.width, max_img_width)
            new_height = int(new_width / img_aspect_ratio)
        else:
            new_height = min(img.height, max_img_height)
            new_width = int(new_height * img_aspect_ratio)
        img = img.resize((new_width, new_height), Image.LANCZOS)

        # Generate audio for the slide using Google TTS
        slide_audio_path = os.path.join(audio_folder, f"{listing_id}_{product_id}_slide_{i+1}.mp3")
        audio_path = create_audio_with_gtts(slide_text, slide_audio_path)
        if audio_path:
            audio_clip = AudioFileClip(audio_path)

            # Prepare video canvas
            img_pil = Image.new('RGB', (1280, 720), color=(255, 255, 255))
            draw = ImageDraw.Draw(img_pil)

            # Add TrustClarity logo to the top-left corner
            img_pil.paste(logo, (20, 20), logo)

            # Add Title text at the top center
            title_font = ImageFont.truetype(title_font_path, 38)
            title_width, title_height = draw.textbbox((0, 0), title, font=title_font)[2:]
            draw.text((50, 200), title, font=title_font, fill="black")

            # Draw slide text
            lines = slide_text.split('\n')
            text_x, text_y = 50, (720 - sum(font.getbbox(line)[3] + 10 for line in lines)) // 2
            for line in lines:
                draw.text((text_x, text_y), line, font=font, fill="black")
                text_y += font.getbbox(line)[3] + 10

            # Place resized image on the right
            img_pil.paste(img, (1280 - new_width - 50, (720 - new_height) // 2))

            # Convert to video clip
            img_np = np.array(img_pil)
            image_clip = ImageSequenceClip([img_np], durations=[audio_clip.duration])
            video_clips.append(image_clip.set_duration(audio_clip.duration))
            audio_clips.append(audio_clip)

    # Combine clips into a single video
    if video_clips:
        final_video = concatenate_videoclips(video_clips, method="compose").set_audio(concatenate_audioclips(audio_clips))
        final_video.write_videofile(os.path.join(output_folder, f"{listing_id}_{product_id}.mp4"), fps=24, audio_codec='aac')
        print(f"Video for listingId {listing_id} and productId {product_id} created at {output_folder}")
    else:
        print(f"No valid images or audio for listingId {listing_id} and productId {product_id}")

# === Batch Pipeline ===

def create_videos_and_blogs_from_csv(input_csv_file, images_data, products_df, output_base_folder):
    """
    This function reads a CSV file containing 'product_id' and 'listing_id',
    checks for available images , Title and descriptions, and creates videos and blog posts for those products.
    The videos and blog posts are saved in folders named as 'listingId_productId'.
    """
    import os

    # # Read the input CSV file
    # product_list = pd.read_csv(input_csv_file)

    # Convert images_data to a dictionary for quick lookup
    # Key: (listing_id, product_id), Value: images
    image_data_dict = {}
    for item in images_data:
        listing_id = item.get('listingId')
        product_id = item.get('productId')
        images = item.get('images')
        if listing_id and product_id and images:
            key = (listing_id, product_id)
            image_data_dict[key] = images

    # # Loop over each product in the input CSV file
    # for index, row in product_list.iterrows():
    #     listing_id = int(row['listing_id'])
    #     product_id = int(row['product_id'])
    #     key = (listing_id, product_id)

        # Check for images
        images = image_data_dict.get(key)
        if not images:
            print(f"No images found for Listing Id: {listing_id}, Product Id: {product_id}")
            continue  # Skip to the next product

        # Check for title and description
        product_row = products_df[
            (products_df['Listing Id'] == listing_id) & (products_df['Product Id'] == product_id)
        ]
        if product_row.empty:
            print(f"No product data found for Listing Id: {listing_id}, Product Id: {product_id}")
            continue  # Skip to the next product

        # Override title to be a combination of 'Brand' and 'MPN'
        brand = product_row['Brand'].values[0] if 'Brand' in products_df.columns else None
        mpn = product_row['MPN'].values[0] if 'MPN' in products_df.columns else None
        title = f"{brand} - {mpn}" if brand and mpn else None


        # title = product_row['Title'].values[0] if 'Title' in products_df.columns else None
        description = product_row['Description'].values[0] if 'Description' in products_df.columns else None

        if pd.isnull(title) or not str(title).strip():
            print(f"No title found for Listing Id: {listing_id}, Product Id: {product_id}")
            continue  # Skip to the next product
        if pd.isnull(description) or not str(description).strip():
            print(f"No description found for Listing Id: {listing_id}, Product Id: {product_id}")
            continue  # Skip to the next product

        # Create the output folder if it doesn't exist
        # print(listing_id)
        # print(product_id)

        output_folder = os.path.join(output_base_folder, f"{listing_id}_{product_id}")
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)
            print(f"Created folder: {output_folder}")

            # Proceed to create the video
            create_video_for_product(listing_id, product_id, title, description, images, output_folder)
            print(f"Video created for Listing Id: {listing_id}, Product Id: {product_id} in folder {output_folder}")
        else:
            print(f"Folder {output_folder} already exists. Skipping video creation.")

        # Generate the blog post
        prompt = f"""You are a professional content writer for TrustClarity Inc.
        Write a detailed and engaging blog article with an apt and adept title about the following product:

        Title: {title}

        Description: {description}

        Please ensure the content is original, informative, and appealing to potential customers. Include any relevant details from the description, and maintain a professional and persuasive tone."""

        blog_content = get_chatgpt_response(prompt)

        # Save the blog content to a text file
        blog_file_path = os.path.join(output_folder, f"{listing_id}_{product_id}.txt")
        with open(blog_file_path, 'w', encoding='utf-8') as blog_file:
            blog_file.write(blog_content)
        print(f"Blog post created for Listing Id: {listing_id}, Product Id: {product_id} at {blog_file_path}")

        # Save the title to a separate text file
        title_file_path = os.path.join(output_folder, f"{listing_id}_{product_id}_title.txt")
        with open(title_file_path, 'w', encoding='utf-8') as title_file:
            title_file.write(title)
        print(f"Title saved for Listing Id: {listing_id}, Product Id: {product_id} at {title_file_path}")

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
