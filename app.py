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

# Set default in drive_db
drive_db.DRIVE_FOLDER_ID = drive_folder_id

# Explicitly create/find sub-folders under your root
inputs_id   = drive_db.find_or_create_folder("inputs",  parent_id=drive_folder_id)
outputs_id  = drive_db.find_or_create_folder("outputs", parent_id=drive_folder_id)
fonts_id    = drive_db.find_or_create_folder("fonts",   parent_id=drive_folder_id)
logo_id     = drive_db.find_or_create_folder("logo",    parent_id=drive_folder_id)

@st.cache_data
def list_drive(mime_filter, parent_id):
    return drive_db.list_files(mime_filter=mime_filter, parent_id=parent_id)

# ─── Mode Selection ───────────────────────────────────────────────────────────
mode = st.sidebar.radio("Mode", ["Single Product", "Batch from CSV"])

# ─── Single Product ──────────────────────────────────────────────────────────
if mode == "Single Product":
    st.header("Single Product Video Generation")

    listing_id  = st.text_input("Listing ID")
    product_id  = st.text_input("Product ID")
    title       = st.text_input("Product Title")
    description = st.text_area("Product Description", height=150)

    # Select images from inputs folder
    img_files = list_drive("image/", inputs_id)
    img_names = [f["name"] for f in img_files]
    selected  = st.multiselect("Select product images", img_names)

    if st.button("Generate Video"):
        if not (listing_id and product_id and title and description and selected):
            st.error("Please fill all fields and select at least one image.")
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                # 1) Download images
                images = []
                for name in selected:
                    meta = next(f for f in img_files if f["name"] == name)
                    buf  = drive_db.download_file(meta["id"])
                    path = os.path.join(tmpdir, name)
                    with open(path, "wb") as f:
                        f.write(buf.read())
                    images.append({"imageURL": path})

                # 2) Download & unzip fonts.zip if present
                font_zips = list_drive("application/zip", fonts_id)
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

                # 3) Download & process logo
                logo_files = list_drive("image/", logo_id)
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

                # 4) Patch audio & output folders
                vgs.audio_folder  = tmpdir
                vgs.output_folder = tmpdir

                # 5) Generate video
                create_video_for_product(
                    listing_id    = listing_id,
                    product_id    = product_id,
                    title         = title,
                    text          = description,
                    images        = images,
                    output_folder = tmpdir,
                )

                # 6) Upload video back to Drive
                video_name = f"{listing_id}_{product_id}.mp4"
                video_path = os.path.join(tmpdir, video_name)
                if os.path.exists(video_path):
                    data = open(video_path, "rb").read()
                    drive_db.upload_file(
                        name      = video_name,
                        data      = data,
                        mime_type = "video/mp4",
                        parent_id = outputs_id,
                    )
                    st.success(f"✅ Uploaded {video_name}")
                    st.video(video_path)
                else:
                    st.error("❌ Video generation failed.")

# ─── Batch from CSV ───────────────────────────────────────────────────────────
else:
    st.header("Batch Video & Blog Generation from CSV")

    csv_files  = list_drive("text/csv", inputs_id)
    csv_name   = st.selectbox("Choose Products CSV", [f["name"] for f in csv_files])
    json_files = list_drive("application/json", inputs_id)
    json_name  = st.selectbox("Choose Images JSON (optional)", ["(none)"] + [f["name"] for f in json_files])

    if st.button("Run Batch"):
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1) Download CSV
            cmeta = next(f for f in csv_files if f["name"] == csv_name)
            cbuf  = drive_db.download_file(cmeta["id"])
            csvp  = os.path.join(tmpdir, csv_name)
            with open(csvp, "wb") as cf:
                cf.write(cbuf.read())
            vgs.csv_file = csvp
            df = pd.read_csv(csvp)

            # 2) Download images JSON
            images_data = {}
            if json_name != "(none)":
                jmeta = next(f for f in json_files if f["name"] == json_name)
                jbuf  = drive_db.download_file(jmeta["id"])
                jp    = os.path.join(tmpdir, json_name)
                with open(jp, "wb") as jf:
                    jf.write(jbuf.read())
                vgs.images_json = jp
                images_data = json.load(open(jp))

            # 3) Download & unzip fonts
            font_zips = list_drive("application/zip", fonts_id)
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

            # 4) Download & process logo
            logo_files = list_drive("image/", logo_id)
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

            # 5) Patch audio & output folders
            vgs.audio_folder  = tmpdir
            vgs.output_folder = tmpdir

            # 6) Run batch
            create_videos_and_blogs_from_csv(
                input_csv_file     = csvp,
                images_data        = images_data,
                products_df        = df,
                output_base_folder = tmpdir,
            )

            # 7) Upload generated videos
            uploaded = []
            for fname in os.listdir(tmpdir):
                if fname.lower().endswith(".mp4"):
                    data = open(os.path.join(tmpdir, fname), "rb").read()
                    drive_db.upload_file(
                        name      = fname,
                        data      = data,
                        mime_type = "video/mp4",
                        parent_id = outputs_id,
                    )
                    uploaded.append(fname)

            if uploaded:
                st.success(f"✅ Uploaded {len(uploaded)} videos")
            else:
                st.error("❌ No videos were generated.")
