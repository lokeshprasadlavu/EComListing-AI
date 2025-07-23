from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from backend.video_generation_service import generate_video, ServiceConfig, GenerationError

import os
import sys  
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

app = FastAPI()

# Input schema for API request
class GenerateRequest(BaseModel):
    csv_file: str
    images_json: str
    audio_folder: str
    fonts_zip_path: str
    logo_path: str
    output_base_folder: str

    listing_id: Optional[str]
    product_id: Optional[str]
    title: str
    description: str
    image_urls: List[str]

# Output schema (optional but useful)
class GenerateResponse(BaseModel):
    video_path: str
    title_file: str
    blog_file: str

@app.post("/generate", response_model=GenerateResponse)
def generate_endpoint(payload: GenerateRequest):
    try:
        cfg = ServiceConfig(
            csv_file=payload.csv_file,
            images_json=payload.images_json,
            audio_folder=payload.audio_folder,
            fonts_zip_path=payload.fonts_zip_path,
            logo_path=payload.logo_path,
            output_base_folder=payload.output_base_folder
        )

        result = generate_video(
            cfg=cfg,
            listing_id=payload.listing_id,
            product_id=payload.product_id,
            title=payload.title,
            description=payload.description,
            image_urls=payload.image_urls
        )

        return GenerateResponse(**result.__dict__)
    except GenerationError as ge:
        raise HTTPException(status_code=400, detail=str(ge))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")
