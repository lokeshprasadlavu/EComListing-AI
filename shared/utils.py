import logging as log
import re
import zipfile
import requests
from typing import List, Dict
import fastjsonschema
from fastjsonschema import JsonSchemaException

import shared.drive_db as drive_db
from shared.drive_db import list_files, download_file, find_or_create_folder, _get_service
from googleapiclient.http import MediaIoBaseDownload
from io import BytesIO

# ─── Image Download (for batch mode) ───
def download_images(image_urls: List[str]) -> List[bytes]:
    """
    Downloads images from URLs and returns list of image bytes.
    Used in batch mode only.
    """
    local_files = []
    for url in image_urls:
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            local_files.append(resp.content)
        except Exception as e:
            log.info(f"Warning: failed to download image {url}: {e}")
    if not local_files:
        raise RuntimeError("All image downloads failed – please check your URLs or network.")
    return local_files

# ─── Fonts & Logo ───
def load_fonts_from_drive(fonts_folder_id: str) -> Dict[str, bytes]:
    files = list_files(parent_id=fonts_folder_id)
    zip_file = next((f for f in files if f["name"].lower().endswith(".zip")), None)
    if not zip_file:
        raise RuntimeError("No font ZIP found in Drive folder.")
    try:
        zip_data = download_file(zip_file["id"])
        with zipfile.ZipFile(zip_data) as zf:
            return {
                name: zf.read(name)
                for name in zf.namelist()
                if name.lower().endswith(".ttf")
            }
    except zipfile.BadZipFile:
        raise RuntimeError("The ZIP file is corrupted.")
    except Exception as e:
        raise RuntimeError(f"Failed to load fonts from Drive: {e}")

def load_logo_from_drive(logo_folder_id: str) -> bytes:
    imgs = list_files(mime_filter='image/', parent_id=logo_folder_id)
    if not imgs:
        raise RuntimeError("No logo image found in logo folder.")
    buf = download_file(imgs[0]['id'])
    return buf.read()

# ─── JSON Schema Validator ───
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
    compiled = fastjsonschema.compile(images_json_schema["items"])
    if not isinstance(data, list):
        raise ValueError("❌ Invalid Images JSON.")
    for idx, entry in enumerate(data, start=1):
        try:
            compiled(entry)
        except JsonSchemaException as e:
            lid = entry.get("listingId")
            pid = entry.get("productId")
            ident = f"(listingId={lid}, productId={pid})" if lid and pid else f"# {idx}"
            raise ValueError(f"❌ Invalid Images JSON at {ident}: {e.message}")

# ─── Filename Helper ───
def slugify(text: str) -> str:
    s = re.sub(r'[^a-zA-Z0-9]+', '_', text)
    return s.strip('_').lower()

# ─── Upload Outputs ───
def upload_output_files_to_drive(file_map: Dict[str, bytes], parent_folder: str, base_name: str):
    """
    Uploads output files to Drive at: outputs/{base_name}/
    """
    folder_id = find_or_create_folder(base_name, parent_id=parent_folder)

    for filename, data in file_map.items():
        mime = 'video/mp4' if filename.endswith('.mp4') else 'text/plain'
        try:
            drive_db.upload_file(name=filename, data=data, mime_type=mime, parent_id=folder_id)
            log.info(f"✅ Uploaded to Drive: {base_name}/{filename}")
        except Exception as e:
            log.error(f"❌ Failed to upload {filename}: {e}")

# ─── Retrieve Output Files ───
# def retrieve_output_files_from_drive(folder_name: str, parent_folder: str) -> Dict[str, bytes]:
#     """
#     Returns output files from Drive folder: outputs/{folder_name}/
#     For use in frontend app to fetch generated content.
#     """
#     folder_id = drive_db.find_folder(folder_name, parent_id=parent_folder)
#     if not folder_id:
#         raise RuntimeError(f"⚠️ Output folder '{folder_name}' not found in Drive.")

#     files = list_files(parent_id=folder_id)
#     outputs = {}

#     for f in files:
#         name = f["name"]
#         try:
#             buf = download_file(f["id"])
#             outputs[name] = buf.read()
#         except Exception as e:
#             log.warning(f"⚠️ Failed to download {name} from {folder_name}: {e}")
    # return outputs

def retrieve_and_stream_output_files(folder_name: str, parent_folder: str) -> dict:
    """
    Retrieves output files (video, blog) from Google Drive folder and streams them directly
    without storing them locally.
    Differentiates between video and blog based on mimeType.
    """
    # Get the folder ID from Drive
    folder_id = drive_db.find_folder(folder_name, parent_id=parent_folder)
    if not folder_id:
        raise RuntimeError(f"⚠️ Output folder '{folder_name}' not found in Drive.")
    
    # Get the list of files in the folder
    files = list_files(parent_id=folder_id)
    outputs = {"video": [], "blog": []}

    # Loop over files and stream them directly based on mimeType
    for f in files:
        name = f["name"]
        mime_type = f["mimeType"]
        try:
            # Check mimeType to differentiate between video and blog content
            if "video" in mime_type:
                # Stream video file
                video_stream = _stream_file(f["id"])
                outputs["video"].append(video_stream) # Assign the video file stream
            elif "text" in mime_type or "document" in mime_type:
                # Stream blog content (txt or other document)
                blog_stream = _stream_file(f["id"])
                outputs["blog"].append(blog_stream)  # Assign the blog file stream
            else:
                log.warning(f"⚠️ Skipping unsupported file type: {name}")
        except Exception as e:
            log.warning(f"⚠️ Failed to download {name} from {folder_name}: {e}")
    return outputs

def _stream_file(file_id):
    """
    Helper function to stream a file from Google Drive using the provided drive service.
    """
    try:
        # Create request to fetch the file
        request = _get_service().files().get_media(fileId=file_id)
        fh = BytesIO()  # Use an in-memory file handle to store the streamed content

        # Use MediaIoBaseDownload to stream the file in chunks
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()  # Stream in chunks

        fh.seek(0)  # Reset cursor to the start of the file for reading
        return fh  # Return the file handle, which can be used for streaming
    except Exception as e:
        log.error(f"Failed to stream file {file_id} from Drive: {e}")
        raise RuntimeError(f"⚠️ Failed to stream file from Drive: {e}")
