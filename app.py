import os
import json
import tempfile

import streamlit as st
import pandas as pd

import video_generation_service as vgs
from video_generation_service import (
    create_video_for_product,
    create_videos_and_blogs_from_csv,
)
import drive_db

# ─── Page Config & Auth ──────────────────────────────────────────────────────
st.set_page_config(page_title="AI Video Generator (Drive-Backed)", layout="wide")
st.title("📹 AI Video Generator")

# Load secrets
OPENAI_API_KEY  = st.secrets["OPENAI_API_KEY"]
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]
# Export OpenAI
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
# Configure drive_db with your folder
drive_db.DRIVE_FOLDER_ID = DRIVE_FOLDER_ID

# ─── Drive Listing Helper ────────────────────────────────────────────────────
@st.cache_data
def get_drive_files(mime_filter=None):
    files = drive_db.list_files()
    if mime_filter:
        return [f for f in files if f.get("mimeType", "").startswith(mime_filter)]
    return files

# ─── Mode Selection ───────────────────────────────────────────────────────────
mode = st.sidebar.radio("Mode", ["Single Product", "Batch from CSV"])

# ─── Single Product Mode ─────────────────────────────────────────────────────
if mode == "Single Product":
    st.header("Single Product Video Generation")

    # Inputs
    listing_id  = st.text_input("Listing ID")
    product_id  = st.text_input("Product ID")
    title       = st.text_input("Product Title")
    description = st.text_area("Product Description", height=150)

    # Pick images from Drive
    image_files = get_drive_files(mime_filter="image/")
    image_names = [f["name"] for f in image_files]
    selected    = st.multiselect("Select product images", image_names)

    if st.button("Generate Video"):
        if not (listing_id and product_id and title and description and selected):
            st.error("Please fill all fields and select at least one image.")
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Download images into tmpdir
                images = []
                for name in selected:
                    meta = next(f for f in image_files if f["name"] == name)
                    buf  = drive_db.download_file(meta["id"])
                    path = os.path.join(tmpdir, name)
                    with open(path, "wb") as f:
                        f.write(buf.read())
                    images.append({"imageURL": path})

                # Patch backend globals
                vgs.AUDIO_FOLDER  = tmpdir
                vgs.FONTS_FOLDER  = tmpdir
                vgs.LOGO_PATH     = None

                # Generate locally
                create_video_for_product(
                    listing_id   = listing_id,
                    product_id   = product_id,
                    title        = title,
                    text         = description,
                    images       = images,
                    output_folder= tmpdir,
                )

                # Upload result back to Drive
                video_name = f"{listing_id}_{product_id}.mp4"
                video_path = os.path.join(tmpdir, video_name)
                if os.path.exists(video_path):
                    with open(video_path, "rb") as vf:
                        data = vf.read()
                    drive_db.upload_file(video_name, data, mime_type="video/mp4")
                    st.success(f"✅ Video generated & uploaded as {video_name}")
                    st.video(video_path)
                else:
                    st.error("❌ Video generation failed.")

# ─── Batch from CSV Mode ─────────────────────────────────────────────────────
else:
    st.header("Batch Video & Blog Generation from CSV")

    # Pick CSV & JSON from Drive
    csv_opts  = get_drive_files(mime_filter="text/csv")
    csv_choice= st.selectbox("Select Products CSV", [f["name"] for f in csv_opts])
    json_opts = get_drive_files(mime_filter="application/json")
    json_choice = st.selectbox(
        "Select Images JSON (optional)", ["(none)"] + [f["name"] for f in json_opts]
    )

    if st.button("Run Batch"):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Download CSV
            csv_meta = next(f for f in csv_opts if f["name"] == csv_choice)
            buf      = drive_db.download_file(csv_meta["id"])
            csv_path = os.path.join(tmpdir, csv_choice)
            with open(csv_path, "wb") as f:
                f.write(buf.read())

            # Download JSON if chosen
            images_data = {}
            if json_choice != "(none)":
                json_meta = next(f for f in json_opts if f["name"] == json_choice)
                jbuf      = drive_db.download_file(json_meta["id"])
                json_path = os.path.join(tmpdir, json_choice)
                with open(json_path, "wb") as jf:
                    jf.write(jbuf.read())
                images_data = json.load(open(json_path))

            # Patch backend globals
            vgs.AUDIO_FOLDER  = tmpdir
            vgs.FONTS_FOLDER  = tmpdir
            vgs.LOGO_PATH     = None

            # Load DataFrame & run batch
            df = pd.read_csv(csv_path)
            create_videos_and_blogs_from_csv(
                input_csv_file     = csv_path,
                images_data        = images_data,
                products_df        = df,
                output_base_folder = tmpdir,
            )

            # Upload all .mp4 results
            uploaded = []
            for fname in os.listdir(tmpdir):
                if fname.lower().endswith(".mp4"):
                    path = os.path.join(tmpdir, fname)
                    with open(path, "rb") as vf:
                        data = vf.read()
                    drive_db.upload_file(fname, data, mime_type="video/mp4")
                    uploaded.append(fname)

            if uploaded:
                st.success(f"✅ Uploaded {len(uploaded)} videos back to Drive")
            else:
                st.error("❌ No videos were generated")
