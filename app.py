import os
import json
import glob
import tempfile
import uuid
import hashlib

import streamlit as st
import pandas as pd

from config import load_config
from auth import get_openai_client, init_drive_service
import drive_db
from utils import (
    temp_workspace, slugify, validate_images_json,
    preload_fonts_from_drive, preload_logo_from_drive
)
from video_generation_service import generate_for_single, generate_batch_from_csv, ServiceConfig, GenerationError

# ─── Persistent Cache Helper ───
def get_persistent_cache_dir(subdir: str):
    cache_dir = os.path.join(tempfile.gettempdir(), 'ecomlisting_cache', subdir)
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir

# ─── Config and Services ───
cfg = load_config()
openai = get_openai_client(cfg.openai_api_key)

drive_db.DRIVE_FOLDER_ID = cfg.drive_folder_id
with st.spinner("🔄 Connecting to Drive…"):
    try:
        svc = init_drive_service(oauth_cfg=cfg.oauth, sa_cfg=cfg.service_account)
        drive_db.set_drive_service(svc)
    except Exception as e:
        st.error(f"⚠️ Drive initialization error: {e}")
        st.stop()

try:
    outputs_id = drive_db.find_or_create_folder("outputs", parent_id=cfg.drive_folder_id)
    fonts_id = drive_db.find_or_create_folder("fonts", parent_id=cfg.drive_folder_id)
    logo_id = drive_db.find_or_create_folder("logo", parent_id=cfg.drive_folder_id)
except Exception as e:
    st.error(f"⚠️ Drive folder setup failed: {e}")
    st.stop()

fonts_folder = preload_fonts_from_drive(fonts_id)
logo_path = preload_logo_from_drive(logo_id)

# ─── Session State ───
def init_session_state():
    defaults = {
        "output_options": "Video + Blog",
        "show_output_radio_single": False,
        "show_output_radio_batch": False,
        "last_single_result": None,
        "last_batch_folder": None,
        "title": "",
        "description": "",
        "uploaded_image_paths": [],
        "batch_csv_path": None,
        "batch_json_path": None,
        "batch_images_data": [],
        "batch_csv_file_path": None,
        "batch_json_file_path": None,
        "last_mode": "Single Product",
        "input_signature": None,
    }
    for key, val in defaults.items():
        st.session_state.setdefault(key, val)

init_session_state()

# ─── Page Config ───
st.set_page_config(page_title="EComListing AI", layout="wide")
st.title("EComListing AI")
st.markdown("🚀 AI-Powered Multimedia Content for your eCommerce Listings.")

# ─── Mode ───
mode = st.sidebar.radio("Choose Mode", ["Single Product", "Batch of Products"], key="app_mode")
if st.session_state.last_mode != mode:
    st.session_state.update({
        "title": "", "description": "", "uploaded_image_paths": [],
        "batch_csv_path": None, "batch_json_path": None,
        "batch_images_data": [], "last_single_result": None,
        "last_batch_folder": None,
        "show_output_radio_single": False,
        "show_output_radio_batch": False,
    })
    st.session_state.last_mode = mode

# ─── Utilities ───
def render_single_output():
    result = st.session_state.last_single_result
    if result:
        st.subheader(result.title)
        if st.session_state.output_options in ("Video only", "Video + Blog"):
            st.video(result.video_path)
        if st.session_state.output_options in ("Blog only", "Video + Blog"):
            st.markdown("**Blog Content**")
            st.write(open(result.blog_file, 'r', encoding='utf-8').read())

def render_batch_output():
    folder = st.session_state.last_batch_folder
    if not folder:
        return
    for sub in os.listdir(folder):
        subdir = os.path.join(folder, sub)
        if not os.path.isdir(subdir):
            continue
        st.subheader(f"Results for {sub}")
        vid = os.path.join(subdir, f"{sub}.mp4")
        blog = os.path.join(subdir, f"{sub}_blog.txt")
        if st.session_state.output_options in ("Video only", "Video + Blog") and os.path.exists(vid):
            st.video(vid)
        if st.session_state.output_options in ("Blog only", "Video + Blog") and os.path.exists(blog):
            st.markdown("**Blog Content**")
            st.write(open(blog, 'r', encoding='utf-8').read())

# ─── Single Product Mode ───
if mode == "Single Product":
    st.header("🎯 Single Product Generation")

    title = st.text_input("Product Title", st.session_state.title)
    description = st.text_area("Product Description", height=150, value=st.session_state.description)
    uploaded_images = st.file_uploader("Upload Product Images (JPG/PNG)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)

    saved_paths = []
    if uploaded_images:
        for img in uploaded_images:
            ext = os.path.splitext(img.name)[1]
            filename = f"{uuid.uuid4().hex}{ext}"
            path = os.path.join(tempfile.gettempdir(), filename)
            with open(path, "wb") as f:
                f.write(img.getvalue())
            saved_paths.append(path)

    if st.button("Generate"):
        input_signature = hashlib.md5((title + description + "".join(sorted([img.name for img in uploaded_images]))).encode()).hexdigest()
        if st.session_state.input_signature != input_signature:
            st.session_state.update({
                "title": title,
                "description": description,
                "uploaded_image_paths": saved_paths,
                "show_output_radio_single": True,
                "last_single_result": None,
                "input_signature": input_signature
            })

    if st.session_state.show_output_radio_single:
        st.session_state.output_options = st.radio(
            "Choose outputs to render:",
            ("Video only", "Blog only", "Video + Blog"),
            index=("Video only", "Blog only", "Video + Blog").index(st.session_state.output_options)
        )

        if st.button("Continue", key="continue_single"):
            slug = slugify(st.session_state.title)
            with temp_workspace() as tmpdir:
                image_urls = []
                for path in st.session_state.uploaded_image_paths:
                    if os.path.exists(path):
                        dst_path = os.path.join(tmpdir, os.path.basename(path))
                        with open(path, 'rb') as src, open(dst_path, 'wb') as dst:
                            dst.write(src.read())
                        image_urls.append(dst_path)

                svc_cfg = ServiceConfig(
                    csv_file='', images_json='',
                    audio_folder=tmpdir,
                    fonts_zip_path=fonts_folder,
                    logo_path=logo_path,
                    output_base_folder=tmpdir,
                )

                try:
                    result = generate_for_single(
                        cfg=svc_cfg,
                        listing_id=None,
                        product_id=None,
                        title=st.session_state.title,
                        description=st.session_state.description,
                        image_urls=image_urls,
                    )
                except GenerationError as ge:
                    st.error(str(ge))
                    st.stop()
                except Exception:
                    st.error("⚠️ Unexpected error. Please check your inputs and try again.")
                    st.stop()

                st.session_state.last_single_result = result
                render_single_output()

                prod_f = drive_db.find_or_create_folder(slug, parent_id=outputs_id)
                try:
                    for path in [result.video_path, result.title_file, result.blog_file]:
                        mime = 'video/mp4' if path.endswith('.mp4') else 'text/plain'
                        drive_db.upload_file(
                            name=os.path.basename(path),
                            data=open(path, 'rb').read(),
                            mime_type=mime,
                            parent_id=prod_f
                        )
                except Exception as e:
                    st.warning(f"⚠️ Upload to Drive failed: {e}")

# ─── Batch Mode ───
else:
    st.header("📦 Batch Generation")

    up_csv = st.file_uploader("Upload Products CSV", type="csv")
    up_json = st.file_uploader("Upload Images JSON (optional)", type="json")

    if up_csv:
        path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}_{up_csv.name}")
        with open(path, "wb") as f:
            f.write(up_csv.getvalue())
        st.session_state.batch_csv_file_path = path

    if up_json:
        path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}_{up_json.name}")
        with open(path, "wb") as f:
            f.write(up_json.getvalue())
        st.session_state.batch_json_file_path = path

    if st.button("Run Batch"):
        if not st.session_state.batch_csv_file_path:
            st.error("❗Please upload a valid Products CSV.")
            st.stop()

        df = pd.read_csv(st.session_state.batch_csv_file_path)
        df.columns = [c.strip() for c in df.columns]

        required_cols = {"Listing Id", "Product Id", "Title", "Description"}
        missing = required_cols - set(df.columns)
        if missing:
            st.error(f"❌ CSV is missing required columns: {', '.join(missing)}")
            st.stop()

        img_col = next((c for c in df.columns if "image" in c.lower() and "url" in c.lower()), None)
        images_data = []

        if img_col is None:
            if not st.session_state.batch_json_file_path:
                st.error("❗Provide either image URLs in CSV or upload a valid JSON file.")
                st.stop()

            images_data = json.load(open(st.session_state.batch_json_file_path))
            try:
                with st.spinner("Validating Images JSON..."):
                    validate_images_json(images_data)
            except ValueError as e:
                st.error(str(e))
                st.stop()

        st.session_state.batch_images_data = images_data
        st.session_state.batch_csv_path = st.session_state.batch_csv_file_path
        st.session_state.batch_json_path = st.session_state.batch_json_file_path
        st.session_state.show_output_radio_batch = True
        st.session_state.last_batch_folder = None

    if st.session_state.show_output_radio_batch:
        st.session_state.output_options = st.radio(
            "Choose outputs to render:",
            ("Video only", "Blog only", "Video + Blog"),
            index=("Video only", "Blog only", "Video + Blog").index(st.session_state.output_options)
        )

        if st.button("Continue", key="continue_batch"):
            svc_cfg = ServiceConfig(
                csv_file=st.session_state.batch_csv_path,
                images_json=st.session_state.batch_json_path,
                audio_folder=os.path.dirname(st.session_state.batch_csv_path),
                fonts_zip_path=fonts_folder,
                logo_path=logo_path,
                output_base_folder=os.path.dirname(st.session_state.batch_csv_path),
            )

            try:
                generate_batch_from_csv(cfg=svc_cfg, images_data=st.session_state.batch_images_data)
            except GenerationError as ge:
                st.error(str(ge))
                st.stop()

            st.session_state.last_batch_folder = svc_cfg.output_base_folder

            for sub in os.listdir(svc_cfg.output_base_folder):
                subdir = os.path.join(svc_cfg.output_base_folder, sub)
                if not os.path.isdir(subdir):
                    continue

                prod_f = drive_db.find_or_create_folder(sub, parent_id=outputs_id)
                for path in glob.glob(os.path.join(subdir, '*')):
                    if path.lower().endswith(('.mp4', '.txt')):
                        try:
                            mime = 'video/mp4' if path.endswith('.mp4') else 'text/plain'
                            drive_db.upload_file(
                                name=os.path.basename(path),
                                data=open(path, 'rb').read(),
                                mime_type=mime,
                                parent_id=prod_f
                            )
                        except Exception as e:
                            st.warning(f"⚠️ Failed to upload {os.path.basename(path)}: {e}")

            render_batch_output()
