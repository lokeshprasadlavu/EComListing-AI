# io_utils.py

import os
import re
import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from typing import List
import requests
from jsonschema import validate, Draft7Validator, ValidationError

def ensure_dir(path: str):
    """Create directory if it doesn’t exist."""
    os.makedirs(path, exist_ok=True)
    return path

@contextmanager
def temp_workspace():
    """
    Context manager that yields a fresh temporary directory
    and cleans up on exit.
    """
    td = tempfile.mkdtemp()
    try:
        yield td
    finally:
        shutil.rmtree(td, ignore_errors=True)

def download_images(image_urls: List[str], target_dir: str) -> List[str]:
    """
    Download each URL into target_dir and return list of local file paths.
    Supports local file paths as well as HTTP URLs.
    """
    ensure_dir(target_dir)
    local_paths = []
    for url in image_urls:
        try:
            filename = os.path.basename(url)
            dest = os.path.join(target_dir, filename)
            if os.path.isfile(url):
                shutil.copy(url, dest)
            else:
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    f.write(resp.content)
            local_paths.append(dest)
        except Exception as e:
            print(f"Warning: failed to download image {url}: {e}")
        if not local_paths:
            raise RuntimeError("All image downloads failed – please check your URLs or network.")
        return local_paths

def extract_fonts(zip_path: str, extract_to: str):
    """
    Unzip a font ZIP (e.g. Poppins.zip) into a folder.
    Overwrites any existing files.
    """
    try:
        ensure_dir(extract_to)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_to)
        return extract_to
    except zipfile.BadZipFile:
        raise RuntimeError(f"Font archive is invalid or corrupted: {zip_path}")
    except Exception as e:
        raise RuntimeError(f"Could not extract fonts from {zip_path}: {e}")

def slugify(text: str) -> str:
    """
    Convert arbitrary text into a filesystem‐ and URL‐friendly slug.
    """
    s = re.sub(r'[^a-zA-Z0-9]+', '_', text)
    return s.strip('_').lower()

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
    from utils import images_json_schema  # if your schema is there

    if not isinstance(data, list):
        raise ValidationError("❌ Invalid JSON")

    validator = Draft7Validator(images_json_schema["items"])

    for idx, entry in enumerate(data):
        errors = list(validator.iter_errors(entry))
        if errors:
            e = errors[0]

            # Try to fetch listingId/productId from the faulty entry
            lid = entry.get("listingId")
            pid = entry.get("productId")

            # If not present, fallback to adjacent valid entries
            if not lid or not pid:
                if idx > 0:
                    prev = data[idx - 1]
                    lid = lid or prev.get("listingId")
                    pid = pid or prev.get("productId")
                elif idx + 1 < len(data):
                    nxt = data[idx + 1]
                    lid = lid or nxt.get("listingId")
                    pid = pid or nxt.get("productId")

            # Build a readable location hint
            loc = f"listingId={lid}, productId={pid}" if lid or pid else f"entry #{idx + 1}"

            raise ValidationError(f"❌ Invalid JSON at {loc}: {e.message}")
