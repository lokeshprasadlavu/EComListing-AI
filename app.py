# ─── Monkey‐patch requests.get to support local files ─────────────────────────
import os
import requests
from requests.models import Response

_orig_get = requests.get
def _get_or_file(path, *args, **kwargs):
    # If it's a local filesystem path, read it directly
    if os.path.isfile(path):
        r = Response()
        r.status_code = 200
        r._content   = open(path, "rb").read()
        return r
    # Otherwise delegate to normal HTTP behavior
    return _orig_get(path, *args, **kwargs)

requests.get = _get_or_file

import os
import json
import zipfile
import tempfile

import streamlit as st
import pandas as pd
from PIL import Image

import openai

import drive_db
import video_generation_service as vgs
from video_generation_service import (
    create_video_for_product,
    create_videos_and_blogs_from_csv,
    upload_videos_streamlit,
)

# ─── Page Config & Auth ──────────────────────────────────────────────────────
st.set_page_config(page_title="AI Video Generator", layout="wide")
st.title("📹 AI Video Generator")

# ─── Secrets ─────────────────────────────────────────────────────────────────
openai_api_key  = st.secrets["OPENAI_API_KEY"]
drive_folder_id = st.secrets["DRIVE_FOLDER_ID"]
os.environ["OPENAI_API_KEY"] = openai_api_key
drive_db.DRIVE_FOLDER_ID     = drive_folder_id
openai.api_key = openai_api_key

# ─── Ensure Drive sub‐folders ─────────────────────────────────────────────────
parent_id = drive_folder_id
inputs_id   = drive_db.find_or_create_folder("inputs",  parent_id)
outputs_id  = drive_db.find_or_create_folder("outputs", parent_id)
fonts_id    = drive_db.find_or_create_folder("fonts",   parent_id)
logo_id     = drive_db.find_or_create_folder("logo",    parent_id)

@st.cache_data
def list_drive(mime_filter, parent_id):
    files = drive_db.list_files(mime_filter=mime_filter, parent_id=parent_id)
    st.write(f"DEBUG list_drive(mime={mime_filter}, parent={parent_id}):", [f['name'] for f in files])
    return files

# ─── Preload & Unzip Fonts Once ───────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def preload_fonts(fonts_folder_id):
    workdir = tempfile.mkdtemp()
    st.write("DEBUG preload_fonts: fonts_folder_id =", fonts_folder_id)
    files = drive_db.list_files(mime_filter=None, parent_id=fonts_folder_id)
    st.write("DEBUG preload_fonts: all in fonts folder:", [(f["name"], f["mimeType"]) for f in files])
    zips  = [f for f in files if f["name"].lower().endswith(".zip")]
    st.write("DEBUG preload_fonts: zip candidates:", [f["name"] for f in zips])
    if zips:
        meta = zips[0]
        buf  = drive_db.download_file(meta["id"])
        zp   = os.path.join(workdir, meta["name"])
        with open(zp, "wb") as f: f.write(buf.read())
        extract_dir = os.path.join(workdir, "fonts")
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(zp, "r") as zf:
            zf.extractall(extract_dir)
        st.write("DEBUG preload_fonts: extracted to", extract_dir, os.listdir(extract_dir))
        return extract_dir
    st.warning("⚠️ preload_fonts: no ZIP found, fonts_folder will be empty")
    return workdir

# ─── Preload & Process Logo Once ─────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def preload_logo(logo_folder_id):
    st.write("DEBUG preload_logo: logo_folder_id =", logo_folder_id)
    files = drive_db.list_files(mime_filter="image/", parent_id=logo_folder_id)
    st.write("DEBUG preload_logo: logo files:", [(f["name"], f["mimeType"]) for f in files])
    if not files:
        st.warning("⚠️ preload_logo: no logo found")
        return None, None, 0, 0
    meta = files[0]
    buf  = drive_db.download_file(meta["id"])
    workdir = tempfile.mkdtemp()
    lp = os.path.join(workdir, meta["name"])
    with open(lp, "wb") as f: f.write(buf.read())
    img = Image.open(lp).convert("RGBA")
    img.thumbnail((150, 150))
    img.save(lp)
    st.write("DEBUG preload_logo: processed logo at", lp, "size", img.size)
    return img, lp, img.size[0], img.size[1]

# Run preloads
fonts_folder_dir = preload_fonts(fonts_id)
vgs.fonts_folder = fonts_folder_dir

logo_img, logo_path, logo_w, logo_h = preload_logo(logo_id)
vgs.logo        = logo_img
vgs.logo_path   = logo_path
vgs.logo_width  = logo_w
vgs.logo_height = logo_h

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

    # Images via uploader
    uploaded_images = st.file_uploader(
        "Upload product images (PNG/JPG)",
        accept_multiple_files=True,
        type=["png", "jpg", "jpeg"]
    )

    if st.button("Generate Video"):
        st.write("DEBUG: Starting generation with tmpdir etc.")
        if not (listing_id and product_id and title and description and uploaded_images):
            st.error("Please fill all fields and upload ≥1 image.")
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                st.write("DEBUG tmpdir created:", tmpdir)

                # Save images
                images = []
                for up in uploaded_images:
                    p = os.path.join(tmpdir, up.name)
                    with open(p, "wb") as f: f.write(up.getbuffer())
                    images.append({"imageURL": p})
                st.write("DEBUG saved images:", images, os.listdir(tmpdir))

                # Verify fonts_folder is populated
                st.write("DEBUG vgs.fonts_folder:", vgs.fonts_folder, os.listdir(vgs.fonts_folder))

                # Verify logo
                st.write("DEBUG logo_path:", vgs.logo_path, "exists?", os.path.exists(vgs.logo_path))

                # Patch audio & output
                vgs.audio_folder  = tmpdir
                vgs.output_folder = tmpdir
                st.write("DEBUG audio_folder:", vgs.audio_folder, os.listdir(vgs.audio_folder))

                # Pre-generate context dump
                st.write("### 🔍 DEBUGGING CONTEXT BEFORE GENERATION")
                st.write("tmpdir contents:", os.listdir(tmpdir))
                st.write("images list:", images)
                st.write("fonts_folder contents:", os.listdir(vgs.fonts_folder))
                st.write("logo_path:", vgs.logo_path)

                # Generate
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
                    st.error(f"Error during video generation: {e}")
                    raise

                # Post-generate check
                mp4s = [f for f in os.listdir(tmpdir) if f.lower().endswith(".mp4")]
                st.write("DEBUG tmpdir after generation:", os.listdir(tmpdir))
                if not mp4s:
                    st.error("❌ No .mp4 generated.")
                else:
                    fn   = mp4s[0]
                    path = os.path.join(tmpdir, fn)
                    data = open(path, "rb").read()
                    drive_db.upload_file(fn, data, "video/mp4", parent_id=outputs_id)
                    st.success(f"✅ Uploaded {fn}")
                    st.video(path)

# ─── Batch from CSV Mode ─────────────────────────────────────────────────────
else:
    st.header("Batch Video & Blog Generation from CSV")
    st.write("""Upload a CSV file with product details and optionally a JSON file with image URLs.
The CSV should have columns like `listing_id`, `product_id`, `title`, and `description`.
The JSON file can contain image URLs or paths for each product, structured as a dictionary with `listing_id` as keys and lists of image URLs as values.""")


    uploaded_csv  = st.file_uploader("Upload Products CSV", type="csv")
    uploaded_json = st.file_uploader("Upload Images JSON (optional)", type="json")

    if st.button("Run Batch"):
        if not uploaded_csv:
            st.error("Please upload a Products CSV to proceed.")
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Load and normalize CSV
                csv_path = os.path.join(tmpdir, uploaded_csv.name)
                with open(csv_path, "wb") as f:
                    f.write(uploaded_csv.getbuffer())
                df = pd.read_csv(csv_path)
                df.columns = [c.strip() for c in df.columns]
                rename_map = {k: v for k, v in [
                    ("listing_id", "Listing Id"),
                    ("product_id", "Product Id"),
                    ("title", "Title"),
                    ("description", "Description"),
                ] if k in df.columns}
                if rename_map:
                    df = df.rename(columns=rename_map)

                # Load images JSON
                images_data = []
                if uploaded_json:
                    json_path = os.path.join(tmpdir, uploaded_json.name)
                    with open(json_path, "wb") as f:
                        f.write(uploaded_json.getbuffer())
                    images_data = json.load(open(json_path))

                # Iterate each product
                for _, row in df.iterrows():
                    lid  = row.get("Listing Id")
                    pid  = row.get("Product Id")
                    title = row.get("Title")
                    desc  = row.get("Description")

                    st.subheader(f"{title} — [{lid}/{pid}]")
                    st.write(desc)

                    # Build image list from JSON entries
                    imgs = []
                    if isinstance(images_data, list):
                        match = next((item for item in images_data \
                             if item.get("listingId") == lid), None)
                        if match:
                            for imgobj in match.get("images", []):
                                url = imgobj.get("imageURL")
                                if not url:
                                    continue
                                resp = requests.get(url)
                                fn = os.path.basename(url)
                                p  = os.path.join(tmpdir, fn)
                                with open(p, "wb") as f:
                                    f.write(resp.content)
                                imgs.append({"imageURL": p})

                    st.write(f"DEBUG built imgs for {lid}:", imgs)
                    if not imgs:
                        st.warning(f"No images for {lid}; skipping.")
                        continue

                    # Patch folders
                    vgs.audio_folder  = tmpdir
                    vgs.output_folder = tmpdir

                    # Generate per-product
                    try:
                        create_video_for_product(
                            listing_id    = lid,
                            product_id    = pid,
                            title         = title,
                            text          = desc,
                            images        = imgs,
                            output_folder = tmpdir,
                        )
                    except Exception as e:
                        st.error(f"Failed to generate for {lid}/{pid}: {e}")
                        continue

                    # Preview and upload
                    vid_name = f"{lid}_{pid}.mp4"
                    vid_path = os.path.join(tmpdir, vid_name)
                    if os.path.exists(vid_path):
                        st.video(vid_path)
                        data = open(vid_path, "rb").read()
                        drive_db.upload_file(vid_name, data, "video/mp4", parent_id=outputs_id)
                        st.success(f"Uploaded {vid_name}")
                    else:
                        st.error(f"No video file found for {lid}/{pid}")