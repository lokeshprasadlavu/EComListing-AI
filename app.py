import os
import json
import re
import shutil
import tempfile
import uuid
import hashlib

import streamlit as st
import pandas as pd

import time
from streamlit.runtime.scriptrunner import RerunException
from streamlit.runtime.runtime import Runtime

from config import load_config
from auth import get_openai_client, init_drive_service
import drive_db
from utils import slugify, validate_images_json, preload_fonts_from_drive, preload_logo_from_drive, upload_output_files_to_drive
from video_generation_service import generate_video, ServiceConfig, GenerationError

import logging

# ─── Logger Setup ───
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Persistent Upload Cache
upload_cache_root = "upload_cache"
shutil.rmtree(upload_cache_root, ignore_errors=True)
os.makedirs(upload_cache_root, exist_ok=True)

# Session Helpers
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
        st.session_state.pop(key, None)

def detect_and_reset_on_input_change(context_id: str, input_parts: list):
    combined = ''.join(sorted(input_parts))
    input_hash = hashlib.md5(combined.encode()).hexdigest()
    hash_key = f"previous_input_hash_{context_id}"

    if st.session_state.get(hash_key) != input_hash:
        full_reset_session_state()
        st.session_state[hash_key] = input_hash

INACTIVITY_TIMEOUT_SECONDS = 5 * 60  # 20 minutes

def handle_inactivity():
    now = time.time()
    last_touch = st.session_state.get("last_interaction", now)

    if now - last_touch > INACTIVITY_TIMEOUT_SECONDS:
        st.session_state.clear()

        # Inject JS to reload the page
        st.markdown("""
            <meta http-equiv="refresh" content="0">
            <script>window.location.reload(true);</script>
        """, unsafe_allow_html=True)
        st.stop()

    st.session_state["last_interaction"] = now


# File & Output Helpers
def save_uploaded_file(uploaded_file):
    path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}_{uploaded_file.name}")
    with open(path, "wb") as f:
        f.write(uploaded_file.getvalue())
    return path

def prepare_image_paths(uploaded_images):
    saved_paths = []
    for img in uploaded_images:
        ext = os.path.splitext(img.name)[1]
        filename = f"{uuid.uuid4().hex}{ext}"
        path = os.path.join(tempfile.gettempdir(), filename)
        with open(path, "wb") as f:
            f.write(img.getvalue())
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

    # Check if all expected outputs exist
    if all(os.path.exists(p) for p in [video_path, blog_path, title_path]):
        log.info(f"✅ Loaded from cache: {slug}")
        return type('Result', (), {
            'video_path': video_path,
            'blog_file': blog_path,
            'title_file': title_path
        })()

    # Log which files are missing
    missing = [p for p in [video_path, blog_path, title_path] if not os.path.exists(p)]
    log.info(f"🔄 Cache miss for {slug}. Missing: {', '.join(os.path.basename(f) for f in missing)}")
    
    return generate_video(
        cfg=cfg,
        title=title,
        description=description,
        image_urls=image_urls,
        listing_id=listing_id,
        product_id=product_id,
    )


def display_generated_output(result):
    if st.session_state.output_options in ("Video only", "Video + Blog"):
        st.video(result.video_path)
    if st.session_state.output_options in ("Blog only", "Video + Blog"):
        st.markdown("**Blog Content**")
        st.write(open(result.blog_file, 'r').read())

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

# ⚙️ Config and Services
st.set_page_config(page_title="EComListing AI", layout="wide")
handle_inactivity() 
st.title("EComListing AI")
st.markdown("🚀 AI-Powered Multimedia Content for your eCommerce Listings.")

cfg = load_config()
openai = get_openai_client(cfg.openai_api_key)

with st.spinner("🔄 Connecting to Drive…"):
    try:
        svc = init_drive_service(oauth_cfg=cfg.oauth, sa_cfg=cfg.service_account)
        drive_db.set_drive_service(svc)
    except Exception as e:
        st.error(f"⚠️ Drive initialization error: {e}")
        st.stop()

outputs_id = drive_db.find_or_create_folder("outputs", parent_id=cfg.drive_folder_id)
fonts_id = drive_db.find_or_create_folder("fonts", parent_id=cfg.drive_folder_id)
logo_id = drive_db.find_or_create_folder("logo", parent_id=cfg.drive_folder_id)
fonts_folder = preload_fonts_from_drive(fonts_id)
logo_path = preload_logo_from_drive(logo_id)

# 🔘 Mode Selection
if "last_mode" not in st.session_state:
    st.session_state.last_mode = "Single Product"

mode = st.sidebar.radio("Choose Mode", ["Single Product", "Batch of Products"], key="app_mode")

if st.session_state.last_mode != mode:
    full_reset_session_state()
    st.session_state.last_mode = mode

# Single Product Mode
if mode == "Single Product":
    st.header("🎯 Single Product Generation")

    title = st.text_input("Product Title", st.session_state.get("title", ""))
    description = st.text_area("Product Description", height=150, value=st.session_state.get("description", ""))
    uploaded_images = st.file_uploader("Upload Product Images (JPG/PNG)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)

    detect_and_reset_on_input_change("single", [title, description] + [f.name for f in uploaded_images or []])

    if st.button("Generate"):
        if not title.strip() or not description.strip():
            st.error("❗ Please enter both title and description.")
            st.stop()
        if not uploaded_images:
            st.error("❗ Please upload at least one image.")
            st.stop()

        saved_paths = prepare_image_paths(uploaded_images)
        st.session_state.uploaded_image_paths = saved_paths
        st.session_state.show_output_radio_single = True

    if st.session_state.get("show_output_radio_single"):
        st.session_state.output_options = st.radio("Choose outputs:", ("Video only", "Blog only", "Video + Blog"), index=2)

        if st.button("Continue", key="continue_single"):
            slug = slugify(title)
            output_dir = os.path.join(tempfile.gettempdir(), "outputs", slug)
            os.makedirs(output_dir, exist_ok=True)

            image_urls = st.session_state.uploaded_image_paths

            svc_cfg = build_service_config(output_dir)

            try:
                result = generate_video_cached(
                    cfg=svc_cfg,
                    title=title,
                    description=description,
                    image_urls=image_urls,
                    slug=slug,
                    listing_id=None,
                    product_id=None
                )

                st.session_state.last_single_result = result
                st.subheader("Generated Output")
                display_generated_output(result)
                upload_and_cleanup(os.path.join(upload_cache_root, slug), [result.video_path, result.blog_file, result.title_file], outputs_id)
            except GenerationError:
                st.error("⚠️ Generation failed. Please refresh and try again. If the issue persists, contact support.")

# ✅ Batch Product Mode
else:
    st.header("📦 Batch Generation")

    up_csv = st.file_uploader("Upload Products CSV", type="csv")
    up_json = st.file_uploader("Upload Images JSON (optional)", type="json")

    csv_name = up_csv.name if up_csv else ""
    json_name = up_json.name if up_json else ""
    detect_and_reset_on_input_change("batch", [csv_name, json_name])

    if up_csv:
        st.session_state.batch_csv_file_path = save_uploaded_file(up_csv)

    if up_json:
        st.session_state.batch_json_file_path = save_uploaded_file(up_json)

    if st.button("Run Batch"):
        if not st.session_state.get("batch_csv_file_path"):
            st.error("❗ Please upload a valid Products CSV.")
            st.stop()

        df = pd.read_csv(st.session_state.batch_csv_file_path, low_memory=False)
        df.columns = [c.strip() for c in df.columns]

        required_cols = {"Listing Id", "Product Id", "Title", "Description"}
        missing = required_cols - set(df.columns)
        if missing:
            st.error(f"❌ CSV is missing required columns: {', '.join(missing)}")
            st.stop()

        img_col_exists = any("image" in c.lower() and "url" in c.lower() for c in df.columns)
        images_data = []

        if not img_col_exists and not st.session_state.get("batch_json_file_path"):
            st.error("📂 Provide image URLs in CSV or upload JSON.")
            st.stop()
        elif st.session_state.get("batch_json_file_path"):
            images_data = json.load(open(st.session_state.batch_json_file_path))
            try:
                with st.spinner("Validating Images JSON..."):
                    validate_images_json(images_data)
            except ValueError as e:
                st.error(str(e))
                st.stop()

        st.session_state.update({
            "batch_images_data": images_data,
            "batch_csv_path": st.session_state.get("batch_csv_file_path", ""),
            "batch_json_path": st.session_state.get("batch_json_file_path", ""),
            "show_output_radio_batch": True,
            "last_batch_folder": None,
        })

    if st.session_state.get("show_output_radio_batch"):
        st.session_state.output_options = st.radio("Choose outputs:", ("Video only", "Blog only", "Video + Blog"), index=2)

        if st.button("Continue", key="continue_batch"):
            base_output = os.path.join(tempfile.gettempdir(), "outputs", "batch")
            os.makedirs(base_output, exist_ok=True)

            svc_cfg = build_service_config(base_output, csv_path=st.session_state.batch_csv_path, json_path=st.session_state.batch_json_path)

            df = pd.read_csv(svc_cfg.csv_file, low_memory=False)
            df.columns = [c.strip() for c in df.columns]


            images_data = st.session_state.batch_images_data
            try:
                MAX_FAILS = 3
                for _, row in df.iterrows():
                    lid, pid = str(row["Listing Id"]), str(row["Product Id"])
                    sub = f"{lid}_{pid}"
                    title, desc = str(row["Title"]), str(row["Description"])
                    key = (int(lid), int(pid)) if lid.isdigit() and pid.isdigit() else (lid, pid)

                    urls = []
                    if images_data:
                        for entry in images_data:
                            if (entry["listingId"], entry["productId"]) == key:
                                urls = [img["imageURL"] for img in entry["images"]]
                                break
                    else:
                        urls = extract_image_urls_from_row(row, df.columns)

                    if not urls:
                        st.warning(f"⚠️ Skipping {lid}/{pid} – No valid image URLs")
                        continue
                    if not title or not desc:
                        st.warning(f"⚠️ Skipping {lid}/{pid} – Missing title or description")
                        continue

                    try:
                        result = generate_video_cached(
                            cfg=svc_cfg,
                            title=title,
                            description=desc,
                            image_urls=urls,
                            slug=sub,
                            listing_id=lid,
                            product_id=pid
                        )
                        consecutive_failures = 0
                    except GenerationError as ge:
                        st.warning(f"⚠️ Skipping {sub} – Generation failed.")
                        log.warning(f"[{sub}] GenerationError: {ge}")
                        consecutive_failures += 1
                        if consecutive_failures >= MAX_FAILS:
                            break
                        continue
                    st.subheader(f"Generating for {sub}")
                    display_generated_output(result)
                    upload_and_cleanup(os.path.join(upload_cache_root, sub), [result.video_path, result.blog_file, result.title_file], outputs_id)
            except Exception:
                st.error("⚠️ Batch generation failed due to a technical issue. Please refresh and try again. If the issue persists, contact support.")