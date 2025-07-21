# Refactored `main.py` for NiceGUI (with Single and Batch Modes)

from nicegui import ui
import os
import json
import re
import shutil
import tempfile
import uuid
import hashlib
import pandas as pd
import logging
import time
import gc

from config import load_config
from auth import get_openai_client, init_drive_service
import drive_db
from utils import (
    slugify, validate_images_json, preload_fonts_from_drive, preload_logo_from_drive,
    upload_output_files_to_drive, clear_all_caches
)
from video_generation_service import generate_video, ServiceConfig, GenerationError

# ─── Logger Setup ───
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

session_state = {}
INACTIVITY_TIMEOUT_SECONDS = 5 * 60
last_interaction = time.time()


def handle_inactivity():
    global last_interaction
    now = time.time()
    if now - last_interaction > INACTIVITY_TIMEOUT_SECONDS:
        clear_all_caches()
        session_state.clear()
        ui.open('/')
    last_interaction = now


def full_reset_session_state():
    keys_to_clear = [
        "output_options", "show_output_radio_single", "show_output_radio_batch",
        "last_single_result", "last_batch_folder", "uploaded_image_paths",
        "batch_csv_path", "batch_json_path", "batch_images_data",
        "batch_csv_file_path", "batch_json_file_path", "input_signature",
        "previous_input_hash", "previous_input_hash_single", "previous_input_hash_batch",
        "title", "description"
    ]
    for key in keys_to_clear:
        session_state.pop(key, None)


def detect_and_reset_on_input_change(context_id: str, input_parts: list):
    combined = ''.join(sorted(input_parts))
    input_hash = hashlib.md5(combined.encode()).hexdigest()
    hash_key = f"previous_input_hash_{context_id}"
    if session_state.get(hash_key) != input_hash:
        full_reset_session_state()
        session_state[hash_key] = input_hash


def save_uploaded_file(uploaded_file):
    path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}_{uploaded_file.name}")
    uploaded_file.save(path)
    return path


def prepare_image_paths(uploaded_images):
    saved_paths = []
    for img in uploaded_images:
        ext = os.path.splitext(img.name)[1]
        filename = f"{uuid.uuid4().hex}{ext}"
        path = os.path.join(tempfile.gettempdir(), filename)
        img.save(path)
        saved_paths.append(path)
    return saved_paths


def build_service_config(output_dir, csv_path='', json_path=''):
    return ServiceConfig(
        csv_file=csv_path,
        images_json=json_path,
        audio_folder=output_dir,
        fonts_zip_path=fonts_folder,
        logo_path=logo_path,
        output_base_folder=output_dir,
    )


def generate_video_cached(cfg, title, description, image_urls, slug, listing_id=None, product_id=None):
    work_dir = os.path.join(cfg.output_base_folder, slug)
    video_path = os.path.join(work_dir, f"{slug}.mp4")
    blog_path = os.path.join(work_dir, f"{slug}_blog.txt")
    title_path = os.path.join(work_dir, f"{slug}_title.txt")

    if all(os.path.exists(p) for p in [video_path, blog_path, title_path]):
        log.info(f"✅ Loaded from cache: {slug}")
        result = type('Result', (), {
            'video_path': video_path,
            'blog_file': blog_path,
            'title_file': title_path
        })()
        return result, True

    missing = [p for p in [video_path, blog_path, title_path] if not os.path.exists(p)]
    log.info(f"🔄 Cache miss for {slug}. Missing: {', '.join(os.path.basename(f) for f in missing)}")

    result = generate_video(
        cfg=cfg,
        title=title,
        description=description,
        image_urls=image_urls,
        listing_id=listing_id,
        product_id=product_id,
    )
    return result, False


def display_generated_output(result):
    if session_state['output_options'] in ("Video only", "Video + Blog"):
        ui.video(result.video_path)
    if session_state['output_options'] in ("Blog only", "Video + Blog"):
        with open(result.blog_file, 'r') as f:
            ui.markdown("**Blog Content**\n" + f.read())


def upload_and_cleanup(local_folder, files, drive_folder_id):
    os.makedirs(local_folder, exist_ok=True)
    for f in files:
        shutil.copy(f, os.path.join(local_folder, os.path.basename(f)))
    upload_output_files_to_drive(subdir=local_folder, parent_id=drive_folder_id)
    shutil.rmtree(local_folder, ignore_errors=True)


def extract_image_urls_from_row(row, df_columns):
    col_map = {c.lower(): c for c in df_columns}
    img_col = next((col_map[c] for c in col_map if "image" in c and "url" in c), None)
    if not img_col:
        return []
    raw = str(row.get(img_col, ""))
    split_urls = re.split(r"[,\n;]", raw)
    return [u.strip() for u in split_urls if re.search(r"\.(png|jpe?g)(\?|$)", u, re.IGNORECASE)]


@ui.page('/')
def main():
    handle_inactivity()
    ui.label("EComListing AI").classes("text-2xl font-bold")
    ui.markdown("🚀 AI-Powered Multimedia Content for your eCommerce Listings.")

    cfg = load_config()
    openai = get_openai_client(cfg.openai_api_key)
    svc = init_drive_service(oauth_cfg=cfg.oauth, sa_cfg=cfg.service_account)
    drive_db.set_drive_service(svc)

    outputs_id = drive_db.find_or_create_folder("outputs", parent_id=cfg.drive_folder_id)
    fonts_id = drive_db.find_or_create_folder("fonts", parent_id=cfg.drive_folder_id)
    logo_id = drive_db.find_or_create_folder("logo", parent_id=cfg.drive_folder_id)
    global fonts_folder, logo_path
    fonts_folder = preload_fonts_from_drive(fonts_id)
    logo_path = preload_logo_from_drive(logo_id)

    with ui.tabs().classes("w-full") as tabs:
        with ui.tab("Single Product"):
            title = ui.input("Product Title")
            description = ui.textarea("Product Description")
            uploaded_images = ui.upload(multiple=True)

            def on_generate():
                if not title.value.strip() or not description.value.strip():
                    ui.notify("Please enter both title and description.", type="negative")
                    return
                if not uploaded_images.value:
                    ui.notify("Please upload at least one image.", type="negative")
                    return

                session_state['uploaded_image_paths'] = prepare_image_paths(uploaded_images.value)
                session_state['output_options'] = "Video + Blog"

                slug = slugify(title.value)
                output_dir = os.path.join(tempfile.gettempdir(), "outputs", slug)
                os.makedirs(output_dir, exist_ok=True)

                image_urls = session_state['uploaded_image_paths']
                svc_cfg = build_service_config(output_dir)

                try:
                    result, cache_hit = generate_video_cached(
                        cfg=svc_cfg,
                        title=title.value,
                        description=description.value,
                        image_urls=image_urls,
                        slug=slug,
                    )
                    session_state['last_single_result'] = result
                    display_generated_output(result)
                    if not cache_hit:
                        upload_and_cleanup(os.path.join("upload_cache", slug), [result.video_path, result.blog_file, result.title_file], outputs_id)
                except GenerationError:
                    ui.notify("Generation failed. Please try again.", type="negative")

            ui.button("Generate", on_click=on_generate)

        with ui.tab("Batch Upload"):
            csv_input = ui.upload(label="Upload Products CSV")
            json_input = ui.upload(label="Upload Images JSON (optional)")

            def on_run_batch():
                if not csv_input.value:
                    ui.notify("Please upload a valid Products CSV.", type="negative")
                    return

                csv_path = save_uploaded_file(csv_input.value[0])
                json_path = save_uploaded_file(json_input.value[0]) if json_input.value else ''

                df = pd.read_csv(csv_path, low_memory=False)
                df.columns = [c.strip() for c in df.columns]
                required_cols = {"Listing Id", "Product Id", "Title", "Description"}

                if not required_cols.issubset(df.columns):
                    ui.notify("CSV is missing required columns.", type="negative")
                    return

                images_data = []
                if json_path:
                    with open(json_path, 'r') as jf:
                        images_data = json.load(jf)
                    try:
                        validate_images_json(images_data)
                    except ValueError as e:
                        ui.notify(str(e), type="negative")
                        return

                session_state['output_options'] = "Video + Blog"
                output_dir = os.path.join(tempfile.gettempdir(), "outputs", "batch")
                os.makedirs(output_dir, exist_ok=True)
                svc_cfg = build_service_config(output_dir, csv_path=csv_path, json_path=json_path)

                try:
                    for _, row in df.iterrows():
                        lid, pid = str(row["Listing Id"]), str(row["Product Id"])
                        slug = f"{lid}_{pid}"
                        title = str(row["Title"])
                        description = str(row["Description"])

                        urls = []
                        key = (int(lid), int(pid)) if lid.isdigit() and pid.isdigit() else (lid, pid)
                        if images_data:
                            for entry in images_data:
                                if (entry["listingId"], entry["productId"]) == key:
                                    urls = [img["imageURL"] for img in entry["images"]]
                                    break
                        else:
                            urls = extract_image_urls_from_row(row, df.columns)

                        if not urls or not title or not description:
                            continue

                        try:
                            result, cache_hit = generate_video_cached(
                                cfg=svc_cfg,
                                title=title,
                                description=description,
                                image_urls=urls,
                                slug=slug,
                                listing_id=lid,
                                product_id=pid
                            )
                            display_generated_output(result)
                            if not cache_hit:
                                upload_and_cleanup(os.path.join("upload_cache", slug), [result.video_path, result.blog_file, result.title_file], outputs_id)
                            del result
                            gc.collect()
                        except GenerationError:
                            log.warning(f"Skipping {slug} due to GenerationError")

                except Exception as e:
                    ui.notify("Batch generation failed.", type="negative")
                    log.exception(e)

            ui.button("Run Batch", on_click=on_run_batch)


ui.run(title="EComListing AI", native=False, host='0.0.0.0', port=8080)
