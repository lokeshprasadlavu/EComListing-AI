import logging
import os
import glob
import re
import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from typing import List

import requests
from fastjsonschema import JsonSchemaException
import fastjsonschema
from PIL import Image
from moviepy.editor import ImageClip
import drive_db
from drive_db import list_files, download_file, find_or_create_folder, upload_file

# ─── Logger ───
log = logging.getLogger(__name__)


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)
    return path

def get_persistent_cache_dir(subdir: str):
    from tempfile import gettempdir
    base_dir = os.path.join(gettempdir(), "ecomlisting_cache", subdir)
    return ensure_dir(base_dir)

def extract_fonts(zip_path: str, extract_to: str):
    try:
        ensure_dir(extract_to)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_to)
        return extract_to
    except zipfile.BadZipFile:
        raise RuntimeError(f"❌ Invalid or corrupted font ZIP: {zip_path}")
    except Exception as e:
        raise RuntimeError(f"❌ Could not extract fonts from {zip_path}: {e}")

def preload_fonts_from_drive(fonts_folder_id: str) -> str:
    """Download and extract font ZIP from Drive."""
    font_cache_dir = get_persistent_cache_dir("fonts")
    zips = list_files(parent_id=fonts_folder_id)
    zip_meta = next((f for f in zips if f['name'].lower().endswith('.zip')), None)

    if zip_meta:
        buf = download_file(zip_meta['id'])
        zip_path = os.path.join(font_cache_dir, zip_meta['name'])

        with open(zip_path, 'wb') as f:
            f.write(buf.read())

        fonts_dir = os.path.join(font_cache_dir, 'extracted')
        return extract_fonts(zip_path, fonts_dir)
    
    print("⚠️ No font zip found in Drive folder.")
    return None

def preload_logo_from_drive(logo_folder_id: str) -> str:
    """Download the first image file in the logo folder."""
    logo_cache_dir = get_persistent_cache_dir("logo")
    imgs = list_files(mime_filter='image/', parent_id=logo_folder_id)

    if not imgs:
        print("⚠️ No image found in logo folder.")
        return None

    meta = imgs[0]
    buf = download_file(meta['id'])
    logo_path = os.path.join(logo_cache_dir, meta['name'])

    with open(logo_path, 'wb') as f:
        f.write(buf.read())

    return logo_path

# ─── Other Utilities ───
def slugify(text: str) -> str:
    """Sanitize and slugify a string for filenames or keys."""
    s = re.sub(r'[^a-zA-Z0-9]+', '_', text)
    return s.strip('_').lower()

# ─── JSON Schema Validation ───
images_json_schema = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["listingId", "productId", "images"],
        "properties": {
            "listingId": {"type": "number"},
            "productId": {"type": "number"},
            "images": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["imageURL"],
                    "properties": {
                        "imageURL": {"type": "string", "format": "uri"},
                        "imageFilename": {"type": "string"},
                        "thumbURL": {"type": "string"},
                        "imageKey": {"type": "string"}
                    },
                    "additionalProperties": True
                },
                "minItems": 1
            }
        },
        "additionalProperties": True
    }
}

def validate_images_json(data):
    """Validate JSON image list structure using fastjsonschema."""
    compiled_image_validator = fastjsonschema.compile(images_json_schema["items"])

    if not isinstance(data, list):
        raise ValueError("❌ Invalid Images JSON — expected a list.")

    for idx, entry in enumerate(data, start=1):
        try:
            compiled_image_validator(entry)
        except JsonSchemaException as e:
            lid = entry.get("listingId")
            pid = entry.get("productId")
            identifier = f"(listingId={lid}, productId={pid})" if lid and pid else f"# {idx}"
            raise ValueError(f"❌ Invalid Images JSON at {identifier}: {e.message}")
        
def upload_output_files_to_drive(result=None, parent_drive_id=None, product_slug=None, folder_path=None):
    """Upload result (single) or batch folder to Google Drive."""
    if not parent_drive_id or not product_slug:
        raise ValueError("Missing drive folder or product slug.")

    prod_f = drive_db.find_or_create_folder(product_slug, parent_id=parent_drive_id)

    # If a single result is passed
    if result and hasattr(result, 'video_path'):
        files_to_upload = [
            (result.video_path, "video/mp4"),
            (result.blog_file, "text/plain"),
            (result.title_file, "text/plain"),
        ]
    elif folder_path:
        files_to_upload = [
            (os.path.join(folder_path, f), 'video/mp4' if f.endswith('.mp4') else 'text/plain')
            for f in os.listdir(folder_path)
            if f.lower().endswith(('.mp4', '.txt'))
        ]
    else:
        raise ValueError("Either result or folder_path must be provided.")

    for path, mime in files_to_upload:
        try:
            drive_db.upload_file(
                name=os.path.basename(path),
                data=open(path, 'rb').read(),
                mime_type=mime,
                parent_id=prod_f,
            )
        except Exception as e:
            print(f"⚠️ Failed to upload {os.path.basename(path)}: {e}")

