import os
import sys
import json
import re
import shutil
import tempfile
import uuid
import hashlib
import requests
import streamlit as st
import pandas as pd
import time
import logging
import gc
import psutil

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from shared.config import load_config
from shared.auth import init_drive_service
import shared.drive_db as drive_db
from shared.utils import slugify, validate_images_json, retrieve_and_stream_output_files

# ─── Logger Setup ───
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

try:
    # Session Helpers
    def full_reset_session_state():
        preserved_keys = {"cleared_cache", "last_mode", "last_interaction"}
        
        keys_to_clear = [
            "output_options",
            "show_output_radio_single",
            "show_output_radio_batch",
            "last_single_result",
            "last_batch_folder",
            "uploaded_image_paths",
            "batch_csv_path",
            "batch_json_path",
            "batch_images_data",
            "batch_csv_file_path",
            "batch_json_file_path",
            "input_signature",
            "previous_input_hash",
            "previous_input_hash_single",
            "previous_input_hash_batch",
            "title",
            "description"
        ]

        for key in keys_to_clear:
            if key not in preserved_keys:
                st.session_state.pop(key, None)


    def detect_and_reset_on_input_change(context_id, input_parts):
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
        try: 
            with open(path, "wb") as f:
                f.write(uploaded_file.getvalue())
            return path
        except Exception as e:
            log.error(f"Failed saving uploaded file: {e}")
            st.error("⚠️ File saving failed. Please re-upload.")
            st.stop()

    # def display_output(data):
    #     if st.session_state.output_options in ("Video only", "Video + Blog"):
    #         st.video(data["video_path"])
    #     if st.session_state.output_options in ("Blog only", "Video + Blog"):
    #         st.markdown("**Blog Content**")
    #         st.write(open(data["blog_file"], 'r').read())
    
    def display_output(data):
        """
        Display video and blog content based on session output options.
        Expects `data["folder"]` to be in the form of "outputs/slug".
        """
        folder_path = data.get("folder")
        if not folder_path:
            st.error("⚠️ Missing output folder reference.")
            return

        try:
            # Fetch and stream the files directly from Drive using the updated function
            outputs = retrieve_and_stream_output_files(folder_path, outputs_id)
            log.info(f"Retrieved output files for {folder_path}: {outputs}")
        except Exception as e:
            st.error("⚠️ Failed to retrieve output files from Drive.")
            log.exception("Error fetching files.")
            return

        # Initialize variables to store video and blog content
        video_file = None
        blog_file = None

        # Loop through the files in the outputs dictionary
        for file_name, file_stream in outputs.items():
            try:
                mime_type = file_stream.getbuffer().type  # Get mime type from the stream (if available)

                # If the mime type contains 'video', assign it to video_file
                if 'video' in mime_type.lower():
                    video_file = file_stream  # Assign the video stream

                # If the file name contains '_blog', assign it to blog_file
                elif '_blog' in file_name.lower() and file_name.lower().endswith('.txt'):
                    blog_file = file_stream  # Assign the blog stream

            except Exception as e:
                st.warning(f"⚠️ Failed to display {file_name}: {e}")

        # Display content based on output options
        if st.session_state["output_options"] == "Video only" or st.session_state["output_options"] == "Video + Blog":
            if video_file:
                st.video(video_file)  # Display the video
            else:
                st.warning("⚠️ No video found in the output folder.")

        if st.session_state["output_options"] == "Blog only" or st.session_state["output_options"] == "Video + Blog":
            if blog_file:
                blog_content = blog_file.read().decode('utf-8')
                st.markdown("**Blog Content**")
                st.write(blog_content)  # Display the blog content
            else:
                st.warning("⚠️ No blog found in the output folder.")


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
    
    secrets = st.secrets
    cfg = load_config(secrets)

    with st.spinner("🔄 Connecting to Drive…"):
        try:
            svc = init_drive_service(oauth_cfg=cfg.oauth, sa_cfg=cfg.service_account)
            drive_db.set_drive_service(svc)
        except Exception as e:
            st.error(f"⚠️ Drive initialization error: {e}")
            st.stop()

    outputs_id = drive_db.find_or_create_folder("outputs", parent_id=cfg.drive_folder_id)
    BACKEND_URL = os.getenv("VIDEO_API_URL", "https://your-backend.app/generate")

    class GenerationError(Exception):
        pass

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
        description = st.text_area("Product Description", height=100, value=st.session_state.get("description", ""))
        uploaded_images = st.file_uploader("Upload Product Images (JPG/PNG)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
        detect_and_reset_on_input_change("single", [title, description] + [f.name for f in uploaded_images or []])

        if st.button("Generate"):
            if not title.strip() or not description.strip():
                st.error("❗ Please enter both title and description.")
                st.stop()
            if not uploaded_images:
                st.error("❗ Please upload at least one image.")
                st.stop()
            if any(f is None for f in uploaded_images):
                st.warning("⏳ Please wait for all image uploads to complete.")
                st.stop()
            st.session_state["title"] = title
            st.session_state["description"] = description
            st.session_state["uploaded_images"] = uploaded_images
            st.session_state["show_output_radio_single"] = True

        if st.session_state.get("show_output_radio_single"):
            st.session_state["output_options"]= st.radio("Choose outputs:", ("Video only", "Blog only", "Video + Blog"), index=2)
            if st.button("Continue", key="continue_single"):
                failed = False
                with st.spinner("🎥 Generating content..."):
                    try:
                            slug = slugify(st.session_state["title"])
                            files = [("image_files", (img.name, img, img.type)) for img in st.session_state["uploaded_images"]]
                            payload = {
                                "title": slug,
                                "description": st.session_state["description"]
                            }
                            response = requests.post(BACKEND_URL, data=payload, files=files)
                            response.raise_for_status()
                            response_data = response.json()
                            st.session_state["last_single_result"] = response_data
                    except Exception as e:
                        failed = True
                        log.exception(f"Generation error.{e}")
                        
                if failed:
                    st.error("❌ Generation failed. Please try again.")
                    st.stop()
                else:
                    st.subheader("Generated Output")
                    display_output(response_data)

    # ✅ Batch Product Mode
    else:
        st.header("📦 Batch Generation")

        up_csv = st.file_uploader("Upload Products CSV", type="csv")
        up_json = st.file_uploader("Upload Images JSON (optional)", type="json")

        csv_name = up_csv.name if up_csv else ""
        json_name = up_json.name if up_json else ""
        detect_and_reset_on_input_change("batch", [csv_name, json_name])

        if up_csv:
            st.session_state["batch_csv_file_path"] = save_uploaded_file(up_csv)
        if up_json:
            st.session_state["batch_json_file_path"] = save_uploaded_file(up_json)

        if st.button("Run Batch"):
            if not st.session_state.get("batch_csv_file_path"):
                st.error("❗ Please upload a valid Products CSV.")
                st.stop()
            if up_csv is None or (up_json and not up_json.getvalue()):
                st.warning("⏳ Please wait for all file uploads to complete.")
                st.stop()
            df = pd.read_csv(st.session_state.batch_csv_file_path, low_memory=False)
            gc.collect()
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
                images_data = json.load(open(st.session_state["batch_json_file_path"]))
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
                df = pd.read_csv(st.session_state.batch_csv_file_path, low_memory=False)
                df.columns = [c.strip() for c in df.columns]
                images_data = st.session_state["batch_images_data"]
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
                            response = requests.post(
                                BACKEND_URL,
                                data={
                                    "listing_id": lid,
                                    "product_id": pid,
                                    "title": title,
                                    "description": desc,
                                    "image_urls": json.dumps(urls),
                                }
                            )
                            response.raise_for_status()
                            data = response.json()
                            consecutive_failures = 0
                        except Exception as ge:
                            st.warning(f"⚠️ Skipping {sub} – Generation failed.")
                            log.warning(f"[{sub}] GenerationError: {ge}")
                            consecutive_failures += 1
                            if consecutive_failures >= MAX_FAILS:
                                break
                            continue
                        st.subheader(f"Generated for {sub}")
                        display_output(data)
                        gc.collect()
                except Exception as e:
                    st.error("⚠️ Batch generation failed due to a technical issue. Please refresh and try again. If the issue persists, contact support.")
                    log.exception(f"Batch generation failed: {e}")
except Exception:
    st.error("⚠️ An unexpected error occurred. Please refresh the page or contact support if the issue persists.")
    log.exception("An unexpected error occurred in the main app loop.")