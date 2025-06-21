import os
import io
import json
import zipfile
import tempfile

import streamlit as st
import pandas as pd
from PIL import Image

import video_generation_service as vgs
from video_generation_service import (
    create_video_for_product,
    create_videos_and_blogs_from_csv,
)
import drive_db

# ─── Page Config & Auth ──────────────────────────────────────────────────────
st.set_page_config(page_title="AI Video Generator", layout="wide")
st.title("📹 AI Video Generator")

# Load secrets
openai_api_key  = st.secrets["OPENAI_API_KEY"]
drive_folder_id = st.secrets["DRIVE_FOLDER_ID"]
os.environ["OPENAI_API_KEY"] = openai_api_key
drive_db.DRIVE_FOLDER_ID = drive_folder_id

# Create/find sub-folders under root
inputs_id   = drive_db.find_or_create_folder("inputs",  parent_id=drive_folder_id)
outputs_id  = drive_db.find_or_create_folder("outputs", parent_id=drive_folder_id)
fonts_id    = drive_db.find_or_create_folder("fonts",   parent_id=drive_folder_id)
logo_id     = drive_db.find_or_create_folder("logo",    parent_id=drive_folder_id)

@st.cache_data
def list_drive(mime_filter, parent_id):
    return drive_db.list_files(mime_filter=mime_filter, parent_id=parent_id)

# ─── Mode Selection ───────────────────────────────────────────────────────────
mode = st.sidebar.radio("Mode", ["Single Product", "Batch from CSV"])

# ─── Single Product Mode ─────────────────────────────────────────────────────
if mode == "Single Product":
    st.header("Single Product Video Generation")

    # 1) User inputs
    listing_id  = st.text_input("Listing ID")
    product_id  = st.text_input("Product ID")
    title       = st.text_input("Product Title")
    description = st.text_area("Product Description", height=150)

    # 2) File uploader for product images
    uploaded_images = st.file_uploader(
        "Upload product images (PNG, JPG)", 
        accept_multiple_files=True, 
        type=["png", "jpg", "jpeg"]
    )

    if st.button("Generate Video"):
        if not (listing_id and product_id and title and description and uploaded_images):
            st.error("Please fill all fields and upload at least one image.")
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                # DEBUG: initial tmpdir contents
                st.write("DEBUG: tmpdir at start:", tmpdir, os.listdir(tmpdir))

                # 3) Save uploaded images locally
                images = []
                for up in uploaded_images:
                    img_path = os.path.join(tmpdir, up.name)
                    with open(img_path, "wb") as f:
                        f.write(up.getbuffer())
                    images.append({"imageURL": img_path})
                st.write("DEBUG: saved images:", images, os.listdir(tmpdir))

                # 4) Download & unzip fonts
                all_fonts = list_drive(None, fonts_id)
                st.write("DEBUG: all files in fonts folder:", [(f["name"], f["mimeType"]) for f in all_fonts])
                font_zips = [f for f in all_fonts if f["name"].lower().endswith(".zip")]
                st.write("DEBUG: font_zips found:", [f["name"] for f in font_zips])
                if font_zips:
                    zmeta = font_zips[0]
                    zbuf  = drive_db.download_file(zmeta["id"])
                    zpath = os.path.join(tmpdir, zmeta["name"])
                    with open(zpath, "wb") as zf:
                        zf.write(zbuf.read())
                    with zipfile.ZipFile(zpath, "r") as zf:
                        zf.extractall(os.path.join(tmpdir, "fonts"))
                    vgs.fonts_folder = os.path.join(tmpdir, "fonts")
                else:
                    vgs.fonts_folder = tmpdir
                st.write("DEBUG: vgs.fonts_folder contents:", vgs.fonts_folder, os.listdir(vgs.fonts_folder))

                # 5) Download & process logo
                logo_files = list_drive("image/", logo_id)
                st.write("DEBUG: logo_files:", [(f["name"], f["mimeType"]) for f in logo_files])
                if logo_files:
                    lmeta     = logo_files[0]
                    lbuf      = drive_db.download_file(lmeta["id"])
                    logo_path = os.path.join(tmpdir, lmeta["name"])
                    with open(logo_path, "wb") as lf:
                        lf.write(lbuf.read())

                    logo = Image.open(logo_path).convert("RGBA")
                    logo.thumbnail((150, 150))
                    logo.save(logo_path)

                    vgs.logo       = logo
                    vgs.logo_path  = logo_path
                    vgs.logo_width, vgs.logo_height = logo.size
                else:
                    vgs.logo       = None
                    vgs.logo_path  = None
                    vgs.logo_width = vgs.logo_height = 0
                st.write("DEBUG: logo_path, exists:", vgs.logo_path, os.path.exists(vgs.logo_path))

                # 6) Patch audio & output folders
                vgs.audio_folder  = tmpdir
                vgs.output_folder = tmpdir
                st.write("DEBUG: audio_folder contents:", os.listdir(vgs.audio_folder))

                # 7) Debug full context before generation
                st.write("### 🔍 DEBUGGING CONTEXT BEFORE GENERATE")
                st.write("tmpdir contents:", os.listdir(tmpdir))
                st.write("images list:", images)
                st.write("fonts_folder contents:", os.listdir(vgs.fonts_folder))
                st.write("audio_folder contents:", os.listdir(vgs.audio_folder))
                st.write("logo_path:", vgs.logo_path)

                # 8) Generate video
                try:
                    create_video_for_product(
                        listing_id    = listing_id,
                        product_id    = product_id,
                        title         = title,
                        text          = description,
                        images        = images,
                        output_folder = tmpdir,
                    )
                except Exception as e:
                    st.error(f"🚨 Exception during generation: {e}")
                    raise

                # 9) Check for output
                mp4s = [f for f in os.listdir(tmpdir) if f.lower().endswith(".mp4")]
                if not mp4s:
                    st.error(f"❌ No .mp4 found. tmpdir contents: {os.listdir(tmpdir)}")
                else:
                    video_name = mp4s[0]
                    video_path = os.path.join(tmpdir, video_name)
                    data = open(video_path, "rb").read()
                    drive_db.upload_file(
                        name      = video_name,
                        data      = data,
                        mime_type = "video/mp4",
                        parent_id = outputs_id,
                    )
                    st.success(f"✅ Uploaded {video_name}")
                    st.video(video_path)

# ─── Batch from CSV Mode ─────────────────────────────────────────────────────
else:
    st.header("Batch Video & Blog Generation from CSV")

    # 1) Select CSV & JSON from Drive
    csv_files  = list_drive("text/csv", inputs_id)
    csv_name   = st.selectbox("Choose Products CSV", [f["name"] for f in csv_files])
    json_files = list_drive("application/json", inputs_id)
    json_name  = st.selectbox("Choose Images JSON (optional)", ["(none)"] + [f["name"] for f in json_files])

    if st.button("Run Batch"):
        with tempfile.TemporaryDirectory() as tmpdir:
            st.write("DEBUG Batch tmpdir:", tmpdir, os.listdir(tmpdir))

            # 2) Download CSV
            cmeta = next(f for f in csv_files if f["name"] == csv_name)
            cbuf  = drive_db.download_file(cmeta["id"])
            csvp  = os.path.join(tmpdir, csv_name)
            with open(csvp, "wb") as cf:
                cf.write(cbuf.read())
            vgs.csv_file = csvp
            df = pd.read_csv(csvp)
            st.write("DEBUG: loaded CSV, head:", df.head())

            # 3) Download images JSON
            images_data = {}
            if json_name != "(none)":
                jmeta = next(f for f in json_files if f["name"] == json_name)
                jbuf  = drive_db.download_file(jmeta["id"])
                jp    = os.path.join(tmpdir, json_name)
                with open(jp, "wb") as jf:
                    jf.write(jbuf.read())
                vgs.images_json = jp
                images_data = json.load(open(jp))
            st.write("DEBUG: images_data keys:", list(images_data.keys()))

            # 4) Download & unzip fonts
            all_fonts = list_drive(None, fonts_id)
            st.write("DEBUG Batch fonts folder contents:", [(f["name"], f["mimeType"]) for f in all_fonts])
            font_zips = [f for f in all_fonts if f["name"].lower().endswith(".zip")]
            st.write("DEBUG Batch font_zips:", [f["name"] for f in font_zips])
            if font_zips:
                zmeta = font_zips[0]
                zbuf  = drive_db.download_file(zmeta["id"])
                zpath = os.path.join(tmpdir, zmeta["name"])
                with open(zpath, "wb") as zf:
                    zf.write(zbuf.read())
                with zipfile.ZipFile(zpath, "r") as zf:
                    zf.extractall(os.path.join(tmpdir, "fonts"))
                vgs.fonts_folder = os.path.join(tmpdir, "fonts")
            else:
                vgs.fonts_folder = tmpdir
            st.write("DEBUG: vgs.fonts_folder contents:", os.listdir(vgs.fonts_folder))

            # 5) Download & process logo
            logo_files = list_drive("image/", logo_id)
            st.write("DEBUG Batch logo_files:", [(f["name"], f["mimeType"]) for f in logo_files])
            if logo_files:
                lmeta     = logo_files[0]
                lbuf      = drive_db.download_file(lmeta["id"])
                logo_path = os.path.join(tmpdir, lmeta["name"])
                with open(logo_path, "wb") as lf:
                    lf.write(lbuf.read())

                logo = Image.open(logo_path).convert("RGBA")
                logo.thumbnail((150, 150))
                logo.save(logo_path)

                vgs.logo       = logo
                vgs.logo_path  = logo_path
                vgs.logo_width, vgs.logo_height = logo.size
            else:
                vgs.logo       = None
                vgs.logo_path  = None
                vgs.logo_width = vgs.logo_height = 0
            st.write("DEBUG: logo_path exists?", vgs.logo_path, os.path.exists(vgs.logo_path))

            # 6) Patch audio & output folders
            vgs.audio_folder  = tmpdir
            vgs.output_folder = tmpdir
            st.write("DEBUG: audio_folder contents:", os.listdir(vgs.audio_folder))

            # 7) Generate batch
            try:
                create_videos_and_blogs_from_csv(
                    input_csv_file     = csvp,
                    images_data        = images_data,
                    products_df        = df,
                    output_base_folder = tmpdir,
                )
            except Exception as e:
                st.error(f"🚨 Exception during batch: {e}")
                raise

            # 8) Upload results
            mp4s = [f for f in os.listdir(tmpdir) if f.lower().endswith(".mp4")]
            if not mp4s:
                st.error(f"❌ No .mp4 found in batch. tmpdir contents: {os.listdir(tmpdir)}")
            else:
                for video_name in mp4s:
                    video_path = os.path.join(tmpdir, video_name)
                    data = open(video_path, "rb").read()
                    drive_db.upload_file(
                        name      = video_name,
                        data      = data,
                        mime_type = "video/mp4",
                        parent_id = outputs_id,
                    )
                st.success(f"✅ Uploaded {len(mp4s)} videos: {mp4s}")
