import os
import json
import re
import shutil
import tempfile
import uuid
import hashlib

import streamlit as st
import pandas as pd

from config import load_config
from auth import get_openai_client, init_drive_service
import drive_db
from utils import slugify, validate_images_json, preload_fonts_from_drive, preload_logo_from_drive, upload_output_files_to_drive
from video_generation_service import generate_video, ServiceConfig, GenerationError

# ─── Persistent Upload Cache ───
upload_cache_root = "upload_cache"
shutil.rmtree(upload_cache_root, ignore_errors=True)
os.makedirs(upload_cache_root, exist_ok=True)

# ─── Session Helpers ───
def full_reset_session_state():
    keys_to_clear = [
        "output_options", "show_output_radio_single", "show_output_radio_batch",
        "last_single_result", "last_batch_folder", "uploaded_image_paths",
        "batch_csv_path", "batch_json_path", "batch_images_data",
        "batch_csv_file_path", "batch_json_file_path", "input_signature",
        "previous_input_hash", "title", "description"
    ]
    for key in keys_to_clear:
        st.session_state.pop(key, None)

def detect_and_reset_on_input_change(new_title, new_desc, new_files):
    input_hash = hashlib.md5((new_title + new_desc + "".join(sorted([f.name for f in new_files]))).encode()).hexdigest()
    if st.session_state.get("previous_input_hash") != input_hash:
        full_reset_session_state()
        st.session_state.title = new_title
        st.session_state.description = new_desc
        st.session_state.uploaded_image_paths = []
        st.session_state.previous_input_hash = input_hash

# ─── Config and Services ───
st.set_page_config(page_title="EComListing AI", layout="wide")
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

# ─── Mode Selection ───
if "last_mode" not in st.session_state:
    st.session_state.last_mode = "Single Product"

mode = st.sidebar.radio("Choose Mode", ["Single Product", "Batch of Products"], key="app_mode")

if st.session_state.last_mode != mode:
    full_reset_session_state()
    st.session_state.last_mode = mode

# ─── 🎯 Single Product ───
if mode == "Single Product":
    st.header("🎯 Single Product Generation")

    title = st.text_input("Product Title", st.session_state.get("title", ""))
    description = st.text_area("Product Description", height=150, value=st.session_state.get("description", ""))
    uploaded_images = st.file_uploader("Upload Product Images (JPG/PNG)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)

    detect_and_reset_on_input_change(title, description, uploaded_images or [])

    if st.button("Generate"):
        if not title.strip() or not description.strip():
            st.error("❗ Please enter both title and description.")
            st.stop()
        if not uploaded_images:
            st.error("❗ Please upload at least one image.")
            st.stop()

        saved_paths = []
        for img in uploaded_images:
            ext = os.path.splitext(img.name)[1]
            filename = f"{uuid.uuid4().hex}{ext}"
            path = os.path.join(tempfile.gettempdir(), filename)
            with open(path, "wb") as f:
                f.write(img.getvalue())
            saved_paths.append(path)

        st.session_state.uploaded_image_paths = saved_paths
        st.session_state.input_signature = hashlib.md5((title + description + "".join(sorted([img.name for img in uploaded_images]))).encode()).hexdigest()
        st.session_state.show_output_radio_single = True

    if st.session_state.get("show_output_radio_single"):
        st.session_state.output_options = st.radio("Choose outputs:", ("Video only", "Blog only", "Video + Blog"), index=2)

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

            try:
                result = generate_video(
                    cfg=svc_cfg,
                    listing_id=None,
                    product_id=None,
                    title=st.session_state.title,
                    description=st.session_state.description,
                    image_urls=image_urls,
                )
                st.session_state.last_single_result = result
                st.subheader("Generated Output")
                if st.session_state.output_options in ("Video only", "Video + Blog"):
                    st.video(result.video_path)
                if st.session_state.output_options in ("Blog only", "Video + Blog"):
                    st.markdown("**Blog Content**")
                    st.write(open(result.blog_file, 'r').read())

                upload_folder = os.path.join(upload_cache_root, slug)
                os.makedirs(upload_folder, exist_ok=True)
                for f in [result.video_path, result.blog_file, result.title_file]:
                    shutil.copy(f, os.path.join(upload_folder, os.path.basename(f)))

                upload_output_files_to_drive(subdir=upload_folder, parent_id=outputs_id)

                shutil.rmtree(upload_folder, ignore_errors=True)

            except GenerationError as ge:
                st.error(str(ge))
                st.stop()
            except Exception as e:
                st.error(f"⚠️ Unexpected error: {e}")
                st.stop()

# ─── 📦 Batch Generation ───
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
        if not st.session_state.get("batch_csv_file_path"):
            st.error("❗ Please upload a valid Products CSV.")
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

        if "imageURL" not in df.columns and not st.session_state.get("batch_json_file_path"):
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
            "batch_csv_path": st.session_state.batch_csv_file_path,
            "batch_json_path": st.session_state.batch_json_file_path,
            "show_output_radio_batch": True,
            "last_batch_folder": None,
        })

    if st.session_state.get("show_output_radio_batch"):
        st.session_state.output_options = st.radio("Choose outputs:", ("Video only", "Blog only", "Video + Blog"), index=2)

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

            df = pd.read_csv(svc_cfg.csv_file)
            df.columns = [c.strip() for c in df.columns]
            img_col = next((c for c in df.columns if "image" in c.lower() and "url" in c.lower()), None)
            images_data = st.session_state.batch_images_data

            for _, row in df.iterrows():
                lid, pid = str(row["Listing Id"]), str(row["Product Id"])
                title, desc = str(row["Title"]), str(row["Description"])
                key = (int(lid), int(pid)) if lid.isdigit() and pid.isdigit() else (lid, pid)

                urls = []
                if images_data:
                    for entry in images_data:
                        if (entry["listingId"], entry["productId"]) == key:
                            urls = [img["imageURL"] for img in entry["images"]]
                            break
                elif img_col:
                    raw = str(row[img_col] or "")
                    urls = [u.strip() for u in raw.split(",") if re.search(r"\.(png|jpe?g)(\?|$)", u, re.IGNORECASE)]

                if not urls:
                    st.warning(f"⚠️ Skipping {lid}/{pid} – No valid image URLs")
                    continue
                if not title or not desc:
                    st.warning(f"⚠️ Skipping {lid}/{pid} – Missing title or description")
                    continue

                try:
                    result = generate_video(
                        cfg=svc_cfg,
                        listing_id=lid,
                        product_id=pid,
                        title=title,
                        description=desc,
                        image_urls=urls,
                    )
                except GenerationError as ge:
                    st.warning(f"⚠️ Skipping {lid}/{pid} – {ge}")
                    continue

                sub = f"{lid}_{pid}"
                subdir = os.path.join(base_output, sub)

                # Show UI output immediately
                st.subheader(f"Generating for {sub}")
                if st.session_state.output_options in ("Video only", "Video + Blog") and os.path.exists(result.video_path):
                    st.video(result.video_path)
                if st.session_state.output_options in ("Blog only", "Video + Blog") and os.path.exists(result.blog_file):
                    st.markdown("**Blog Content**")
                    st.write(open(result.blog_file, 'r').read())

                # Upload to Drive immediately
                upload_subdir = os.path.join(upload_cache_root, sub)
                os.makedirs(upload_subdir, exist_ok=True)
                for f in [result.video_path, result.blog_file, result.title_file]:
                    shutil.copy(f, os.path.join(upload_subdir, os.path.basename(f)))

                try:
                    upload_output_files_to_drive(subdir=upload_subdir, parent_id=outputs_id)
                except Exception as e:
                    st.warning(f"⚠️ Upload failed for {sub}: {e}")
                finally:
                    shutil.rmtree(upload_subdir, ignore_errors=True)
