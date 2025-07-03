import logging
import os
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

from drive_db import list_files, download_file

# ─── Logger ───
log = logging.getLogger(__name__)

# ─── File System Utilities ─── 
def ensure_dir(path: str):
    """Ensure a directory exists."""
    os.makedirs(path, exist_ok=True)
    return path

@contextmanager
def temp_workspace():
    """Temporary working directory context."""
    td = tempfile.mkdtemp()
    try:
        yield td
    finally:
        shutil.rmtree(td, ignore_errors=True)

def get_persistent_cache_dir(subdir: str):
    """Returns a persistent cache path under /tmp/ecomlisting_cache/"""
    cache_dir = os.path.join(tempfile.gettempdir(), 'ecomlisting_cache', subdir)
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir

# ─── Downloads ─── 
def download_images(image_urls: List[str], target_dir: str) -> List[str]:
    """Download or copy images to a local directory and return paths."""
    ensure_dir(target_dir)
    local_paths = []
    for url in image_urls:
        try:
            filename = os.path.basename(url)
            dest = os.path.join(target_dir, filename)

            if os.path.isfile(url):  # Local file path
                shutil.copy(url, dest)
            else:  # Remote URL
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    f.write(resp.content)

            local_paths.append(dest)
        except Exception as e:
            log.warning(f"⚠️ Failed to download image: {url} — {e}")

    if not local_paths:
        raise RuntimeError("❌ All image downloads failed – check your URLs or network.")
    
    return local_paths

# ─── Fonts & Logo Preload ───
def extract_fonts(zip_path: str, extract_to: str):
    """Extract a .zip of fonts into a folder."""
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
    
    log.warning("No font zip found in Drive folder.")
    return None

def preload_logo_from_drive(logo_folder_id: str) -> str:
    """Download the first image file in the logo folder."""
    logo_cache_dir = get_persistent_cache_dir("logo")
    imgs = list_files(mime_filter='image/', parent_id=logo_folder_id)

    if not imgs:
        log.warning("No image found in logo folder.")
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
