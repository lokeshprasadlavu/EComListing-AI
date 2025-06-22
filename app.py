# ─── Monkey‐patch requests.get to support local files ─────────────────────────
import os
import requests
from requests.models import Response

_orig_get = requests.get
def _get_or_file(path, *args, **kwargs):
    if os.path.isfile(path):
        r = Response()
        r.status_code = 200
        r._content = open(path, "rb").read()
        return r
    return _orig_get(path, *args, **kwargs)
requests.get = _get_or_file
# ─────────────────────────────────────────────────────────────────────────────

import json
import zipfile
import tempfile

import streamlit as st
import pandas as pd
import openai
from PIL import Image

import drive_db
import video_generation_service as vgs
from video_generation_service import (
    create_video_for_product,
    create_videos_and_blogs_from_csv,
)

# ─── Page Config & Auth ──────────────────────────────────────────────────────
st.set_page_config(page_title="AI Video Generator", layout="wide")
st.title("📹 AI Video Generator")

# ─── Secrets & OpenAI Setup ──────────────────────────────────────────────────
openai.api_key       = st.secrets["OPENAI_API_KEY"]
os.environ["OPENAI_API_KEY"] = openai.api_key
drive_folder_id      = st.secrets["DRIVE_FOLDER_ID"]

# ─── Drive DB Initialization ─────────────────────────────────────────────────
drive_db.DRIVE_FOLDER_ID = drive_folder_id
def get_folder(name):
    return drive_db.find_or_create_folder(name, parent_id=drive_folder_id)
inputs_id   = get_folder("inputs")
outputs_id  = get_folder("outputs")
fonts_id    = get_folder("fonts")
logo_id     = get_folder("logo")

# ─── Helpers ─────────────────────────────────────────────────────────────────
@st.cache_data
def list_drive(mime_filter, parent_id):
    return drive_db.list_files(mime_filter=mime_filter, parent_id=parent_id)

@st.cache_data(show_spinner=False)
def preload_fonts(fonts_folder_id):
    workdir = tempfile.mkdtemp()
    files   = drive_db.list_files(None, parent_id=fonts_folder_id)
    zips    = [f for f in files if f["name"].lower().endswith(".zip")]
    if zips:
        buf = drive_db.download_file(zips[0]["id"])
        zp  = os.path.join(workdir, zips[0]["name"])
        open(zp, "wb").write(buf.read())
        extract_dir = os.path.join(workdir, "fonts")
        os.makedirs(extract_dir, exist_ok=True)
        zipfile.ZipFile(zp).extractall(extract_dir)
        return extract_dir
    return workdir

@st.cache_data(show_spinner=False)
def preload_logo(logo_folder_id):
    files = drive_db.list_files("image/", parent_id=logo_folder_id)
    if not files:
        return None, None, 0, 0
    buf = drive_db.download_file(files[0]["id"])
    workdir = tempfile.mkdtemp()
    lp = os.path.join(workdir, files[0]["name"])
    open(lp, "wb").write(buf.read())
    img = Image.open(lp).convert("RGBA")
    img.thumbnail((150,150))
    img.save(lp)
    return img, lp, img.size[0], img.size[1]

# ─── Preload Assets ──────────────────────────────────────────────────────────
vgs.fonts_folder   = preload_fonts(fonts_id)
vgs.logo, vgs.logo_path, vgs.logo_width, vgs.logo_height = preload_logo(logo_id)

# ─── Mode Selector ───────────────────────────────────────────────────────────
mode = st.sidebar.radio("Mode", ["Single Product", "Batch from CSV"])

# ─── SINGLE PRODUCT ──────────────────────────────────────────────────────────
if mode == "Single Product":
    st.header("Single Product Video Generation")

    listing_id  = st.text_input("Listing ID")
    product_id  = st.text_input("Product ID")
    title       = st.text_input("Product Title")
    description = st.text_area("Product Description", height=150)

    uploaded_images = st.file_uploader(
        "Upload product images (PNG/JPG)",
        accept_multiple_files=True,
        type=["png","jpg","jpeg"]
    )

    if st.button("Generate Video"):
        if not (listing_id and product_id and title and description and uploaded_images):
            st.error("Fill all fields and upload ≥1 image.")
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Save images
                images = []
                for up in uploaded_images:
                    p = os.path.join(tmpdir, up.name)
                    open(p, "wb").write(up.getbuffer())
                    images.append({"imageURL": p})

                # Patch globals
                vgs.audio_folder  = tmpdir
                vgs.output_folder = tmpdir

                # Generate
                try:
                    create_video_for_product(
                        listing_id, product_id, title,
                        description, images, tmpdir
                    )
                except Exception as e:
                    st.error(f"Generation error: {e}")
                    st.stop()

                # Output folder & upload
                folder_name = f"{listing_id}_{product_id}"
                prod_folder = drive_db.find_or_create_folder(folder_name, parent_id=outputs_id)

                # Preview & upload video
                vid = f"{folder_name}.mp4"
                vp  = os.path.join(tmpdir, vid)
                if os.path.exists(vp):
                    st.subheader(title)
                    st.video(vp)
                    drive_db.upload_file(vid, open(vp,"rb").read(), "video/mp4", prod_folder)
                else:
                    st.error(f"Video {vid} missing")

                # Upload title & blog text
                for suf in ["_title.txt","_blog.txt"]:
                    fn = f"{folder_name}{suf}"
                    fp = os.path.join(tmpdir, fn)
                    if os.path.exists(fp):
                        drive_db.upload_file(fn, open(fp,"rb").read(), "text/plain", prod_folder)

# ─── BATCH FROM CSV ───────────────────────────────────────────────────────────
else:
    st.header("Batch Video Generation from CSV")

    uploaded_csv  = st.file_uploader("Upload Products CSV", type="csv")
    uploaded_json = st.file_uploader("Upload Images JSON (optional)", type="json")

    if st.button("Run Batch"):
        if not uploaded_csv:
            st.error("Please upload a Products CSV.")
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Load & normalize CSV
                csvp = os.path.join(tmpdir, uploaded_csv.name)
                open(csvp,"wb").write(uploaded_csv.getbuffer())
                df = pd.read_csv(csvp)
                cols = df.columns.str.strip().str.lower()
                remap = {}
                if "listing id" in cols:
                    remap[df.columns[cols.get_loc("listing id")]] = "Listing Id"
                if "product id" in cols:
                    remap[df.columns[cols.get_loc("product id")]] = "Product Id"
                if "title" in cols:
                    remap[df.columns[cols.get_loc("title")]] = "Title"
                if remap:
                    df = df.rename(columns=remap)
                # Load JSON
                images_data = []
                if uploaded_json:
                    jp = os.path.join(tmpdir, uploaded_json.name)
                    open(jp,"wb").write(uploaded_json.getbuffer())
                    images_data = json.load(open(jp))

                # Per-product loop
                for _, row in df.iterrows():
                    lid = row["Listing Id"]
                    pid = row["Product Id"]
                    title = row["Title"]

                    st.subheader(title)

                    # Build images list
                    imgs = []
                    if isinstance(images_data, list):
                        lid_str = str(lid)
                        entry = next((i for i in images_data
                                      if str(i.get("listingId"))==lid_str), None)
                        if entry:
                            for obj in entry.get("images", []):
                                url = obj.get("imageURL")
                                if not url: continue
                                resp = requests.get(url)
                                fn   = os.path.basename(url)
                                dst  = os.path.join(tmpdir, fn)
                                open(dst,"wb").write(resp.content)
                                imgs.append({"imageURL": dst})

                    if not imgs:
                        st.warning(f"No images for {lid}; skipped.")
                        continue

                    # Patch & generate
                    vgs.audio_folder  = tmpdir
                    vgs.output_folder = tmpdir
                    try:
                        create_videos_and_blogs_from_csv(
                            input_csv_file     = csvp,
                            images_data        = images_data,
                            products_df        = df,
                            output_base_folder = tmpdir,
                        )
                    except Exception as e:
                        st.error(f"Batch error {lid}/{pid}: {e}")
                        continue

                    # Create subfolder & upload
                    folder_name = f"{lid}_{pid}"
                    prod_folder = drive_db.find_or_create_folder(folder_name, parent_id=outputs_id)

                    # Preview & upload video
                    vid = f"{folder_name}.mp4"
                    vp  = os.path.join(tmpdir, vid)
                    if os.path.exists(vp):
                        st.video(vp)
                        drive_db.upload_file(vid, open(vp,"rb").read(), "video/mp4", prod_folder)
                    else:
                        st.warning(f"Video for {lid} missing")

                    # Upload title text
                    tf = f"{folder_name}_title.txt"
                    tp = os.path.join(tmpdir, tf)
                    if os.path.exists(tp):
                        drive_db.upload_file(tf, open(tp,"rb").read(), "text/plain", prod_folder)
