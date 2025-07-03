import os
import json
import glob
import shutil
import tempfile
import uuid
import hashlib

import streamlit as st
import pandas as pd

from config import load_config
from auth import get_openai_client, init_drive_service
import drive_db
from utils import slugify, validate_images_json, preload_fonts_from_drive, preload_logo_from_drive, upload_output_files_to_drive, temp_workspace
from video_generation_service import generate_for_single, generate_batch_from_csv, ServiceConfig, GenerationError

# ─── Persistent Cache Helper ───
def get_session_path(key, default=None):
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]

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
def reset_session_state():
    keys_to_reset = {
        "title": "",
        "description": "",
        "uploaded_image_paths": [],
        "batch_csv_path": None,
        "batch_json_path": None,
        "batch_images_data": [],
        "last_single_result": None,
        "last_batch_folder": None,
        "show_output_radio_single": False,
        "show_output_radio_batch": False,
        "input_signature": None,
    }
    for k, v in keys_to_reset.items():
        st.session_state[k] = v

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
    reset_session_state()
    st.session_state.last_mode = mode
    st.experimental_rerun()


# ─── Utilities ───
def render_single_output():
    result = st.session_state.last_single_result
    if result:
        st.subheader("Generated Output")
        if st.session_state.output_options in ("Video only", "Video + Blog"):
            st.video(result.video_path)
        if st.session_state.output_options in ("Blog only", "Video + Blog"):
            st.markdown("**Blog Content**")
            st.write(open(result.blog_file, 'r').read())

def render_batch_output():
    folder = st.session_state.last_batch_folder
    if not folder:
        return
    for sub in os.listdir(folder):
        subdir = os.path.join(folder, sub)
        if os.path.isdir(subdir):
            st.subheader(f"Results for {sub}")
            vid = os.path.join(subdir, f"{sub}.mp4")
            blog = os.path.join(subdir, f"{sub}_blog.txt")
            if st.session_state.output_options in ("Video only", "Video + Blog") and os.path.exists(vid):
                st.video(vid)
            if st.session_state.output_options in ("Blog only", "Video + Blog") and os.path.exists(blog):
                st.markdown("**Blog Content**")
                st.write(open(blog, 'r').read())

# --- Reusable Output Selector ---
def select_output_options(default="Video + Blog"):
    return st.radio("Choose outputs:", ("Video only", "Blog only", "Video + Blog"), index=["Video only", "Blog only", "Video + Blog"].index(default))

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
        # Always reset session state for a clean start
        reset_session_state()

        if not title.strip() or not description.strip():
            st.error("❗ Please enter both title and description.")
            st.stop()

        if not uploaded_images:
            st.error("❗ Please upload at least one image.")
            st.stop()

        # Save new inputs to session
        saved_paths = []
        for img in uploaded_images:
            ext = os.path.splitext(img.name)[1]
            filename = f"{uuid.uuid4().hex}{ext}"
            path = os.path.join(tempfile.gettempdir(), filename)
            with open(path, "wb") as f:
                f.write(img.getvalue())
            saved_paths.append(path)

        st.session_state.title = title
        st.session_state.description = description
        st.session_state.uploaded_image_paths = saved_paths
        st.session_state.input_signature = hashlib.md5(
            (title + description + "".join(sorted([img.name for img in uploaded_images]))).encode()
        ).hexdigest()
        st.session_state.show_output_radio_single = True

        # Force rerun to reset UI and reinitialize state cleanly
        st.experimental_rerun()


    if st.session_state.show_output_radio_single:
        st.session_state.output_options = select_output_options(st.session_state.output_options)

        if st.button("Continue", key="continue_single"):
            slug = slugify(st.session_state.title)
            output_dir = os.path.join(tempfile.gettempdir(), "outputs", slug)
            os.makedirs(output_dir, exist_ok=True)

            image_urls = []
            for path in st.session_state.uploaded_image_paths:
                if os.path.exists(path):
                    dst_path = os.path.join(output_dir, os.path.basename(path))
                    shutil.copy(path, dst_path)
                    image_urls.append(dst_path)

            svc_cfg = ServiceConfig(
                csv_file='',
                images_json='',
                audio_folder=output_dir,
                fonts_zip_path=fonts_folder,
                logo_path=logo_path,
                output_base_folder=output_dir,
            )
            if not st.session_state.uploaded_image_paths:
                st.error("❗ No uploaded images found. Please re-upload them.")
                st.stop()

            missing_paths = [p for p in st.session_state.uploaded_image_paths if not os.path.exists(p)]
            if missing_paths:
                st.error("❗ Some uploaded images are missing from memory. Please upload again.")
                st.stop()

            try:
                result = generate_for_single(
                    cfg=svc_cfg,
                    listing_id=None,
                    product_id=None,
                    title=st.session_state.title,
                    description=st.session_state.description,
                    image_urls=image_urls,
                )
                st.session_state.last_single_result = result
                render_single_output()

                # ✅ Upload outputs to Drive
                upload_output_files_to_drive(
                                    subdir=output_dir,
                                    parent_id=outputs_id
                                    )


            except GenerationError as ge:
                st.error(str(ge))
                st.stop()
            except Exception as e:
                st.error(f"⚠️ Unexpected error: {e}")
                st.stop()

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

        st.session_state.last_batch_folder = None
        df = pd.read_csv(st.session_state.batch_csv_file_path)
        df.columns = [c.strip() for c in df.columns]

        required_cols = {"Listing Id", "Product Id", "Title", "Description"}
        missing = required_cols - set(df.columns)
        if missing:
            st.error(f"❌ CSV is missing required columns: {', '.join(missing)}")
            st.stop()

        img_col = next((c for c in df.columns if "image" in c.lower() and "url" in c.lower()), None)
        images_data = []

        if "imageURL" not in df.columns and not st.session_state.batch_json_file_path:
            st.error("📂 Provide image URLs in CSV or upload JSON.")
            st.stop()
        elif st.session_state.batch_json_file_path:
            images_data = json.load(open(st.session_state.batch_json_file_path))
            try:
                with st.spinner("Validating Images JSON..."):
                    validate_images_json(images_data)
            except ValueError as e:
                st.error(str(e))
                st.stop()

        st.session_state.update({
            "batch_images_data": images_data,
            "batch_csv_path": st.session_state.batch_csv_file_path,
            "batch_json_path": st.session_state.batch_json_file_path,
            "show_output_radio_batch": True,
            "last_batch_folder": None,
        })

    if st.session_state.show_output_radio_batch:
        st.session_state.output_options = select_output_options(st.session_state.output_options)

        if st.button("Continue", key="continue_batch"):
            base_output = os.path.join(tempfile.gettempdir(), "outputs", "batch")
            os.makedirs(base_output, exist_ok=True)

            svc_cfg = ServiceConfig(
                csv_file=st.session_state.batch_csv_path,
                images_json=st.session_state.batch_json_path,
                audio_folder=base_output,
                fonts_zip_path=fonts_folder,
                logo_path=logo_path,
                output_base_folder=base_output,
            )

            try:
                generate_batch_from_csv(cfg=svc_cfg, images_data=st.session_state.batch_images_data)
            except GenerationError as ge:
                st.error(str(ge))
                st.stop()

            st.session_state.last_batch_folder = base_output
            render_batch_output()

            # ✅ Upload each folder to Drive
            for subdir in os.listdir(base_output):
                full_path = os.path.join(base_output, subdir)
                if os.path.isdir(full_path):
                    try:
                        upload_output_files_to_drive(
                                subdir=full_path,
                                parent_id=outputs_id
                            )
                    except Exception as e:
                        st.warning(f"⚠️ Failed to upload batch outputs for {subdir}: {e}")

