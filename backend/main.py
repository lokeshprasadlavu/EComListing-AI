from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from typing import List, Optional
import logging
import os
import json

from backend.video_generation_service import (
    generate_video,
    ServiceConfig,
    GenerationError,
    GenerationResult
)
from shared.config import load_config
from shared.auth import init_drive_service
from shared import drive_db

# ─── Logging Setup ───
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ─── FastAPI App ───
app = FastAPI()

# ─── Load Configuration ───
try:
    cfg = load_config()
    drive_service = init_drive_service(oauth_cfg=cfg.oauth, sa_cfg=cfg.service_account)
    drive_db.set_drive_service(drive_service)
    fonts_folder_id = drive_db.find_or_create_folder("fonts", parent_id=cfg.drive_folder_id)
    logo_folder_id = drive_db.find_or_create_folder("logo", parent_id=cfg.drive_folder_id)
    output_folder_id = drive_db.find_or_create_folder("outputs", parent_id=cfg.drive_folder_id)
    openai_api_key = os.getenv("OPENAI_API_KEY")

    service_cfg = ServiceConfig(
        drive_service=drive_service,
        drive_folder_id=cfg.drive_folder_id,
        fonts_folder_id=fonts_folder_id,
        logo_folder_id=logo_folder_id,
        output_folder_id=output_folder_id,
        openai_api_key=openai_api_key,
    )
except Exception as e:
    log.exception(f"❌ Failed to initialize service: {e}")
    raise RuntimeError("Startup configuration error.") from e

# ─── Routes ───

@app.get("/")
def health_check():
    return {"status": "Backend is running ✅"}


@app.post("/generate")
async def generate_endpoint(
    listing_id: Optional[str] = Form(None),
    product_id: Optional[str] = Form(None),
    title: str = Form(...),
    description: str = Form(...),
    image_urls: Optional[str] = Form(None),  # JSON list as string
    image_files: Optional[List[UploadFile]] = File(None)
):
    try:
        # Parse image URLs if provided
        urls = []
        if image_urls:
            try:
                urls = json.loads(image_urls)
                if not isinstance(urls, list):
                    raise ValueError("image_urls must be a list of URLs")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid image_urls: {e}")

        # Read file bytes if provided
        file_bytes = []
        if image_files:
            for f in image_files:
                file_bytes.append(f.file.read())

        if not urls and not file_bytes:
            raise HTTPException(status_code=400, detail="Must provide either image URLs or image files.")

        result: GenerationResult = generate_video(
            cfg=service_cfg,
            listing_id=listing_id,
            product_id=product_id,
            title=title,
            description=description,
            image_urls=urls if urls else None,
            image_files=file_bytes if file_bytes else None
        )

        return JSONResponse({
            "folder": result.folder,
            "video": result.video,
            "blog": result.blog,
            "title": result.title
        })

    except GenerationError as ge:
        log.warning(f"🚫 Generation error: {ge}")
        raise HTTPException(status_code=400, detail=str(ge))
    except Exception as e:
        log.exception("🔥 Internal server error")
        raise HTTPException(status_code=500, detail="Internal server error")
