# io_utils.py

import os
import re
import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from typing import List
import requests
from jsonschema import validate, ValidationError

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

# JSON schema for your images_data array
IMAGE_JSON_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["listingId", "productId", "images"],
        "properties": {
            "listingId": {
                "oneOf": [
                    {"type": "integer"},
                    {"type": "string", "pattern": r"^\d+$"}
                ]
            },
            "productId": {
                "oneOf": [
                    {"type": "integer"},
                    {"type": "string", "pattern": r"^\d+$"}
                ]
            },
            "images": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["imageURL"],
                    "properties": {
                        "imageURL": {"type": "string", "format": "uri"}
                    },
                    "additionalProperties": True
                }
            }
        },
        "additionalProperties": True
    }
}


def validate_images_json(data):
    """
    Raises a jsonschema.ValidationError if `data` does not conform
    to IMAGE_JSON_SCHEMA.
    """
    validate(instance=data, schema=IMAGE_JSON_SCHEMA)
