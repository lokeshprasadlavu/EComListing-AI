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
import tempfile
import zipfile

import streamlit as st
import pandas as pd
import openai
from PIL import Image

import drive_db
import video_generation_service as vgs
from video_generation_service import (
    create_video_for_product,
)

# ─── Page Config & Auth ──────────────────────────────────────────────────────
st.set_page_config(page_title="AI Video Generator", layout="wide")
st.title("📹 AI Video Generator")

# ─── Secrets & OpenAI Setup ──────────────────────────────────────────────────
openai.api_key = st.secrets["OPENAI_API_KEY"]
os.environ["OPENAI_API_KEY"] = openai.api_key

# ─── Drive DB Initialization ─────────────────────────────────────────────────
drive_folder_id = st.secrets["DRIVE_FOLDER_ID"]
drive_db.DRIVE_FOLDER_ID = drive_folder_id
inputs_id   = drive_db.find_or_create_folder("inputs", parent_id=drive_folder_id)
outputs_id  = drive_db.find_or_create_folder("outputs", parent_id=drive_folder_id)
fonts_id    = drive_db.find_or_create_folder("fonts", parent_id=drive_folder_id)
logo_id     = drive_db.find_or_create_folder("logo", parent_id=drive_folder_id)

@st.cache_data
def list_drive(mime_filter, parent_id):
    return drive_db.list_files(mime_filter=mime_filter, parent_id=parent_id)

# ─── Preload & Unzip Fonts Once ───────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def preload_fonts(fonts_folder_id):
    workdir = tempfile.mkdtemp()
    files = drive_db.list_files(None, parent_id=fonts_folder_id)
    zips  = [f for f in files if f["name"].lower().endswith(".zip")]
    if zips:
        buf  = drive_db.download_file(zips[0]["id"])
        zp   = os.path.join(workdir, zips[0]["name"])
        open(zp, "wb").write(buf.read())
        extract_dir = os.path.join(workdir, "fonts")
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(zp, "r") as zf:
            zf.extractall(extract_dir)
        return extract_dir
    return workdir

vgs.fonts_folder = preload_fonts(fonts_id)

# ─── Preload & Process Logo Once ─────────────────────────────────────────────
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
            st.error("Please fill all fields and upload ≥1 image.")
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

                # Upload & preview
                folder = f"{listing_id}_{product_id}"
                prod_f = drive_db.find_or_create_folder(folder, parent_id=outputs_id)

                vid = f"{folder}.mp4"
                vp  = os.path.join(tmpdir, vid)
                if os.path.exists(vp):
                    st.subheader(title)
                    st.video(vp)
                    drive_db.upload_file(vid, open(vp,"rb").read(), "video/mp4", prod_f)
                else:
                    st.error(f"Video {vid} missing")

                # Title & blog
                for suf in ["_title.txt","_blog.txt"]:
                    fn = f"{folder}{suf}"
                    fp = os.path.join(tmpdir, fn)
                    if os.path.exists(fp):
                        drive_db.upload_file(fn, open(fp,"rb").read(), "text/plain", prod_f)

# ─── BATCH MODE (per-product streaming + upload) ───────────────────────────
else:
    st.header("Batch Video Generation from CSV")

    up_csv  = st.file_uploader("Upload Products CSV", type="csv")
    up_json = st.file_uploader("Upload Images JSON (optional)", type="json")

    if st.button("Run Batch"):
        if not up_csv:
            st.error("Upload a Products CSV.")
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Load & normalize CSV
                cp = os.path.join(tmpdir, up_csv.name)
                open(cp, "wb").write(up_csv.getbuffer())
                df = pd.read_csv(cp)
                cols = df.columns.str.strip().str.lower()
                rm = {}
                if "listing id" in cols:
                    rm[df.columns[cols.get_loc("listing id")]] = "Listing Id"
                if "product id" in cols:
                    rm[df.columns[cols.get_loc("product id")]] = "Product Id"
                if "title" in cols:
                    rm[df.columns[cols.get_loc("title")]] = "Title"
                if rm:
                    df = df.rename(columns=rm)

                # Load JSON
                images_data = []
                if up_json:
                    jp = os.path.join(tmpdir, up_json.name)
                    open(jp, "wb").write(up_json.getbuffer())
                    images_data = json.load(open(jp))

                # Iterate each product
                for _, row in df.iterrows():
                    lid   = row["Listing Id"]
                    pid   = row["Product Id"]
                    title = row["Title"]

                    st.subheader(f"Generating {title} ({lid}/{pid})... ")

                    # Build images list
                    imgs = []
                    if isinstance(images_data, list):
                        entry = next((i for i in images_data if str(i.get("listingId")) == str(lid)), None)
                        if entry:
                            for obj in entry.get("images", []):
                                url = obj.get("imageURL")
                                if not url:
                                    continue
                                buf = requests.get(url).content
                                fn  = os.path.basename(url)
                                dst = os.path.join(tmpdir, fn)
                                open(dst, "wb").write(buf)
                                imgs.append({"imageURL": dst})

                    if not imgs:
                        st.warning(f"No images for {lid}; skipping.")
                        continue

                    # Patch globals and generate per-product
                    vgs.audio_folder  = tmpdir
                    vgs.output_folder = tmpdir
                    try:
                        create_video_for_product(
                            listing_id    = lid,
                            product_id    = pid,
                            title         = title,
                            text          = "",  # no description in batch
                            images        = imgs,
                            output_folder = tmpdir,
                        )
                    except Exception as e:
                        st.error(f"Error generating {lid}/{pid}: {e}")
                        continue

                    # Prepare Drive folder
                    folder = f"{lid}_{pid}"
                    prod_f = drive_db.find_or_create_folder(folder, parent_id=outputs_id)

                    # Preview & upload the video
                    vid = f"{folder}.mp4"
                    vp  = os.path.join(tmpdir, vid)
                    if os.path.exists(vp):
                        st.video(vp)
                        drive_db.upload_file(vid, open(vp, "rb").read(), "video/mp4", prod_f)
                    else:
                        st.error(f"Video {vid} missing for {lid}")

                    # Upload title text
                    tf = f"{folder}_title.txt"
                    tp = os.path.join(tmpdir, tf)
                    if os.path.exists(tp):
                        drive_db.upload_file(tf, open(tp, "rb").read(), "text/plain", prod_f)