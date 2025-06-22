
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
from video_generation_service import create_video_for_product, create_videos_and_blogs_from_csv

# ─── Page Config & Auth ──────────────────────────────────────────────────────
st.set_page_config(page_title="AI Video Generator", layout="wide")
st.title("📹 AI Video Generator")

# ─── Secrets & OpenAI Setup ──────────────────────────────────────────────────
openai.api_key = st.secrets["OPENAI_API_KEY"]
os.environ["OPENAI_API_KEY"] = openai.api_key
drive_folder_id = st.secrets["DRIVE_FOLDER_ID"]

# ─── Drive DB Init ───────────────────────────────────────────────────────────
drive_db.DRIVE_FOLDER_ID = drive_folder_id
inputs_id   = drive_db.find_or_create_folder("inputs",  parent_id=drive_folder_id)
outputs_id  = drive_db.find_or_create_folder("outputs", parent_id=drive_folder_id)
fonts_id    = drive_db.find_or_create_folder("fonts",   parent_id=drive_folder_id)
logo_id     = drive_db.find_or_create_folder("logo",    parent_id=drive_folder_id)

@st.cache_data
def list_drive(mime_filter, parent_id):
    return drive_db.list_files(mime_filter=mime_filter, parent_id=parent_id)

@st.cache_data(show_spinner=False)
def preload_fonts(fonts_folder_id):
    wd = tempfile.mkdtemp()
    files = drive_db.list_files(None, parent_id=fonts_folder_id)
    zips = [f for f in files if f["name"].lower().endswith(".zip")]
    if zips:
        buf = drive_db.download_file(zips[0]["id"])
        zp  = os.path.join(wd, zips[0]["name"])
        open(zp, "wb").write(buf.read())
        ext = os.path.join(wd, "fonts")
        os.makedirs(ext, exist_ok=True)
        with zipfile.ZipFile(zp, "r") as zf:
            zf.extractall(ext)
        return ext
    return wd

@st.cache_data(show_spinner=False)
def preload_logo(logo_folder_id):
    files = drive_db.list_files("image/", parent_id=logo_folder_id)
    if not files:
        return None, None, 0, 0
    buf = drive_db.download_file(files[0]["id"])
    wd = tempfile.mkdtemp()
    lp = os.path.join(wd, files[0]["name"])
    open(lp, "wb").write(buf.read())
    img = Image.open(lp).convert("RGBA")
    img.thumbnail((150,150))
    img.save(lp)
    return img, lp, img.size[0], img.size[1]

# ─── Preload assets ──────────────────────────────────────────────────────────
vgs.fonts_folder   = preload_fonts(fonts_id)
vgs.logo, vgs.logo_path, vgs.logo_width, vgs.logo_height = preload_logo(logo_id)

# ─── Mode selector ───────────────────────────────────────────────────────────
mode = st.sidebar.radio("Mode", ["Single Product", "Batch from CSV"])

# ─── Single Product ──────────────────────────────────────────────────────────
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
        if not all([listing_id, product_id, title, description, uploaded_images]):
            st.error("Please fill all fields and upload at least one image.")
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Save images locally
                images = []
                for up in uploaded_images:
                    path = os.path.join(tmpdir, up.name)
                    with open(path, "wb") as f:
                        f.write(up.getbuffer())
                    images.append({"imageURL": path})

                vgs.audio_folder  = tmpdir
                vgs.output_folder = tmpdir

                # Generate the video
                create_video_for_product(
                    listing_id=listing_id,
                    product_id=product_id,
                    title=title,
                    text=description,
                    images=images,
                    output_folder=tmpdir,
                )

                # Preview & upload
                folder = f"{listing_id}_{product_id}"
                prod_f = drive_db.find_or_create_folder(folder, parent_id=outputs_id)

                # Video
                vid = f"{folder}.mp4"
                vid_path = os.path.join(tmpdir, vid)
                if os.path.exists(vid_path):
                    st.subheader(title)
                    st.video(vid_path)
                    drive_db.upload_file(vid, open(vid_path, "rb").read(), "video/mp4", prod_f)
                else:
                    st.error(f"Video {vid} missing")

# ─── Batch from CSV ───────────────────────────────────────────────────────────
else:
    st.header("Batch Video & Blog Generation from CSV")
    up_csv  = st.file_uploader("Upload Products CSV", type="csv")
    up_json = st.file_uploader("Upload Images JSON", type="json")

    if st.button("Run Batch"):
        if not all([up_csv, up_json]):
            st.error("Please upload a Products CSV & Images JSON.")
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Save & load CSV
                csv_path = os.path.join(tmpdir, up_csv.name)
                with open(csv_path, "wb") as f:
                    f.write(up_csv.getbuffer())
                df = pd.read_csv(csv_path)
                df.columns = [c.strip() for c in df.columns]
                lower = [c.lower() for c in df.columns]
                rename_map = {}
                if "listing id" in lower:
                    rename_map[df.columns[lower.index("listing id")]] = "Listing Id"
                if "product id" in lower:
                    rename_map[df.columns[lower.index("product id")]] = "Product Id"
                if "title" in lower:
                    rename_map[df.columns[lower.index("title")]] = "Title"
                if rename_map:
                    df = df.rename(columns=rename_map)

                # Save & load JSON
                images_data = []
                if up_json:
                    json_path = os.path.join(tmpdir, up_json.name)
                    with open(json_path, "wb") as f:
                        f.write(up_json.getbuffer())
                    images_data = json.load(open(json_path))

                # Iterate each product
                for _, row in df.iterrows():
                    lid, pid, title = row["Listing Id"], row["Product Id"], row["Title"]
                    st.subheader(f"Generating {title}...")
                    

                    # Build images list
                    imgs = []
                    if isinstance(images_data, list):
                        entry = next((i for i in images_data 
                                      if str(i.get("listingId")) == str(lid)), 
                                      None
                        )
                        if entry:
                            for obj in entry.get("images", []):
                                url = obj.get("imageURL")
                                if not url: continue
                                data = requests.get(url).content
                                fn   = os.path.basename(url)
                                dst  = os.path.join(tmpdir, fn)
                                with open(dst, "wb") as f:
                                    f.write(data)
                                imgs.append({"imageURL": dst})
                    if not imgs:
                        st.warning(f"No images for {lid}; skipping.")
                        continue

                    vgs.audio_folder  = tmpdir
                    vgs.output_folder = tmpdir

                    # Use batch helper per-product
                    create_videos_and_blogs_from_csv(
                        input_csv_file     = csv_path,
                        images_data        = images_data,
                        products_df        = df,
                        output_base_folder = tmpdir,
                    )

                    # Preview & upload
                    folder = f"{lid}_{pid}"
                    prod_f = drive_db.find_or_create_folder(folder, parent_id=outputs_id)

                    # Video
                    vid = f"{folder}.mp4"
                    vp  = os.path.join(tmpdir, vid)
                    if os.path.exists(vp):
                        st.video(vp)
                        drive_db.upload_file(vid, open(vp, "rb").read(), "video/mp4", prod_f)
                    else:
                        st.warning(f"Video for {lid} missing")

                    # Title & Blog text
                    for fn in os.listdir(tmpdir):
                        if fn.startswith(folder) and fn.lower().endswith(".txt"):
                            fp = os.path.join(tmpdir, fn)
                            drive_db.upload_file(fn, open(fp, "rb").read(), "text/plain", prod_f)
