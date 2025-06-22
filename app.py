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

import io
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
)

# ─── Page Configuration & Authentication ─────────────────────────────────────
st.set_page_config(page_title="AI Video Generator", layout="wide")
st.title("📹 AI Video Generator")

# ─── Secrets & OpenAI Setup ──────────────────────────────────────────────────
openai_api_key  = st.secrets["OPENAI_API_KEY"]
drive_folder_id = st.secrets["DRIVE_FOLDER_ID"]
os.environ["OPENAI_API_KEY"] = openai_api_key
openai.api_key = openai_api_key

# ─── Drive DB Initialization ─────────────────────────────────────────────────
drive_db.DRIVE_FOLDER_ID = drive_folder_id
def get_folder(name):
    return drive_db.find_or_create_folder(name, parent_id=drive_folder_id)
inputs_id  = get_folder("inputs")
outputs_id = get_folder("outputs")
fonts_id   = get_folder("fonts")
logo_id    = get_folder("logo")

@st.cache_data
def list_drive(mime_filter, parent_id):
    return drive_db.list_files(mime_filter=mime_filter, parent_id=parent_id)

# ─── Preload & Unzip Fonts Once ───────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def preload_fonts(fonts_folder_id):
    workdir = tempfile.mkdtemp()
    files = drive_db.list_files(mime_filter=None, parent_id=fonts_folder_id)
    zips  = [f for f in files if f["name"].lower().endswith(".zip")]
    if zips:
        meta = zips[0]
        buf  = drive_db.download_file(meta["id"])
        zp   = os.path.join(workdir, meta["name"])
        with open(zp, "wb") as f:
            f.write(buf.read())
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
    files = drive_db.list_files(mime_filter="image/", parent_id=logo_folder_id)
    if not files:
        return None, None, 0, 0
    meta = files[0]
    buf  = drive_db.download_file(meta["id"])
    workdir = tempfile.mkdtemp()
    lp = os.path.join(workdir, meta["name"])
    with open(lp, "wb") as f:
        f.write(buf.read())
    img = Image.open(lp).convert("RGBA")
    img.thumbnail((150, 150))
    img.save(lp)
    return img, lp, img.size[0], img.size[1]

vgs.logo, vgs.logo_path, vgs.logo_width, vgs.logo_height = preload_logo(logo_id)

# ─── Mode Selector ───────────────────────────────────────────────────────────
mode = st.sidebar.radio("Mode", ["Single Product", "Batch from CSV"])

# ─── Single Product Mode ─────────────────────────────────────────────────────
if mode == "Single Product":
    st.header("Single Product Video Generation")

    listing_id  = st.text_input("Listing ID")
    product_id  = st.text_input("Product ID")
    title       = st.text_input("Product Title")
    description = st.text_area("Product Description", height=150)

    uploaded_images = st.file_uploader(
        "Upload product images (PNG/JPG)",
        accept_multiple_files=True,
        type=["png", "jpg", "jpeg"]
    )

    if st.button("Generate Video"):
        if not (listing_id and product_id and title and description and uploaded_images):
            st.error("Please fill all fields and upload at least one image.")
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Save images locally
                images = []
                for up in uploaded_images:
                    p = os.path.join(tmpdir, up.name)
                    with open(p, "wb") as f: f.write(up.getbuffer())
                    images.append({"imageURL": p})

                # Patch folders
                vgs.audio_folder  = tmpdir
                vgs.output_folder = tmpdir

                # Generate video & blog via backend
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
                    st.error(f"Error during generation: {e}")
                    st.stop()

                # Create product folder and upload outputs
                folder_name = f"{listing_id}_{product_id}"
                prod_folder = drive_db.find_or_create_folder(folder_name, parent_id=outputs_id)
                # Upload and preview video
                video_file = f"{folder_name}.mp4"
                video_path = os.path.join(tmpdir, video_file)
                if os.path.exists(video_path):
                    st.subheader(title)
                    st.video(video_path)
                    drive_db.upload_file(video_file, open(video_path,"rb").read(), "video/mp4", prod_folder)
                # Upload title and blog text
                for suffix in ["_title.txt", "_blog.txt"]:
                    fname = folder_name + suffix
                    fpath = os.path.join(tmpdir, fname)
                    if os.path.exists(fpath):
                        drive_db.upload_file(fname, open(fpath,"rb").read(), "text/plain", prod_folder)

# ─── Batch from CSV Mode ─────────────────────────────────────────────────────
else:
    st.header("Batch Video & Blog Generation from CSV")

    uploaded_csv  = st.file_uploader("Upload Products CSV", type="csv")
    uploaded_json = st.file_uploader("Upload Images JSON (optional)", type="json")

    if st.button("Run Batch"):
        if not uploaded_csv:
            st.error("Please upload a Products CSV to proceed.")
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Load CSV and rename columns as before…
                csv_path = os.path.join(tmpdir, uploaded_csv.name)
                with open(csv_path, "wb") as f: f.write(uploaded_csv.getbuffer())
                df = pd.read_csv(csv_path)
                df.columns = [c.strip() for c in df.columns]
                rename_map = {k: v for k, v in [
                    ("listing_id",  "Listing Id"),
                    ("product_id",  "Product Id"),
                    ("title",       "Title"),
                    ("description", "Description"),
                ] if k in df.columns}
                if rename_map:
                    df = df.rename(columns=rename_map)

                # Load images JSON
                images_data = []
                if uploaded_json:
                    json_path = os.path.join(tmpdir, uploaded_json.name)
                    with open(json_path, "wb") as f: f.write(uploaded_json.getbuffer())
                    images_data = json.load(open(json_path))

                # Process each product
                for _, row in df.iterrows():
                    lid   = row["Listing Id"]
                    pid   = row["Product Id"]
                    title = row["Title"]
                    desc  = row["Description"]

                    st.subheader(f"{title} — [{lid}/{pid}]")

                    # Build images list as before…
                    imgs = []
                    if isinstance(images_data, list):
                        match = next((item for item in images_data if item.get("listingId")==lid), None)
                        if match:
                            for imgobj in match.get("images", []):
                                url = imgobj.get("imageURL")
                                if not url: continue
                                resp = requests.get(url)
                                fn   = os.path.basename(url)
                                p    = os.path.join(tmpdir, fn)
                                with open(p, "wb") as f: f.write(resp.content)
                                imgs.append({"imageURL": p})

                    if not imgs:
                        st.warning(f"No images for {lid}; skipping.")
                        continue

                    # Patch and generate
                    vgs.audio_folder  = tmpdir
                    vgs.output_folder = tmpdir
                    try:
                        create_video_for_product(
                            listing_id    = lid,
                            product_id    = pid,
                            title         = title,
                            text          = desc,
                            images        = imgs,
                            output_folder = tmpdir,
                        )
                        # create_videos_and_blogs_from_csv will have also written out:
                        #   * {lid}_{pid}.mp4
                        #   * {lid}_{pid}_blog.txt
                        #   * {lid}_{pid}_title.txt
                    except Exception as e:
                        st.error(f"Failed to generate for {lid}/{pid}: {e}")
                        continue
                    # 1) Create a Drive folder for this product
                    folder_name = f"{lid}_{pid}"
                    prod_folder = drive_db.find_or_create_folder(folder_name, parent_id=outputs_id)

                    # 2) Upload all files for this product
                    for fname in os.listdir(tmpdir):
                        if not fname.startswith(folder_name + "_"):
                            continue
                        path = os.path.join(tmpdir, fname)
                        mime = "video/mp4" if fname.lower().endswith(".mp4") else "text/plain"
                        with open(path, "rb") as f:
                            data = f.read()
                        drive_db.upload_file(
                            name      = fname,
                            data      = data,
                            mime_type = mime,
                            parent_id = prod_folder,
                        )
                        st.write(f"Uploaded `{fname}` to `{folder_name}`")

                    # 3) Preview the video inline
                    video_file = f"{folder_name}.mp4"
                    video_path = os.path.join(tmpdir, video_file)
                    if os.path.exists(video_path):
                        st.video(video_path)
                    else:
                        st.warning(f"Couldn’t find `{video_file}` to preview.")