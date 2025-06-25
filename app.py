import os
import json
import tempfile
import time
import glob
import re

import streamlit as st
import pandas as pd

from config import load_config
from auth import get_openai_client, init_drive_service
import drive_db
from io_utils import temp_workspace, extract_fonts, slugify
from video_generation_service import generate_for_single, generate_batch_from_csv, ServiceConfig

# ─── Load & validate config ─────────────────────────────────────────────────
cfg = load_config()

# ─── Initialize OpenAI client ─────────────────────────────────────────────────
openai = get_openai_client(cfg.openai_api_key)

# ─── Initialize Drive DB & create top-level folders ────────────────────────────
drive_db.DRIVE_FOLDER_ID = cfg.drive_folder_id
with st.spinner("Connecting to Drive…"):
    try:
        svc = init_drive_service(oauth_cfg=cfg.oauth, sa_cfg=cfg.service_account)
        drive_db.set_drive_service(svc)
    except Exception as e:
        st.error(f"Drive initialization error: {e}")
        st.stop()

outputs_id = drive_db.find_or_create_folder("outputs", parent_id=cfg.drive_folder_id)
fonts_id   = drive_db.find_or_create_folder("fonts",   parent_id=cfg.drive_folder_id)
logo_id    = drive_db.find_or_create_folder("logo",    parent_id=cfg.drive_folder_id)

# ─── Preload fonts & logo ─────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def preload_fonts(fonts_folder_id):
    with temp_workspace() as td:
        zips = drive_db.list_files(parent_id=fonts_folder_id)
        zip_meta = next((f for f in zips if f['name'].lower().endswith('.zip')), None)
        if zip_meta:
            buf = drive_db.download_file(zip_meta['id'])
            zp  = os.path.join(td, zip_meta['name'])
            with open(zp, 'wb') as f: f.write(buf.read())
            return extract_fonts(zp, os.path.join(td, 'fonts'))
    return None

@st.cache_data(show_spinner=False)
def preload_logo(logo_folder_id):
    imgs = drive_db.list_files(mime_filter='image/', parent_id=logo_folder_id)
    if not imgs:
        return None
    meta = imgs[0]
    buf  = drive_db.download_file(meta['id'])
    with temp_workspace() as td:
        lp = os.path.join(td, meta['name'])
        with open(lp, 'wb') as f: f.write(buf.read())
        return lp

fonts_folder = preload_fonts(fonts_id)
logo_path    = preload_logo(logo_id)

# ─── Page Config ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="EComListing AI", layout="wide")
st.title("EComListing AI")
st.markdown("AI-Powered Multimedia Content for your eCommerce Listings.")

# ─── Mode Selector ───────────────────────────────────────────────────────────
mode = st.sidebar.radio("Mode", ["Single Product", "Batch of Products"])

# ─── Single Product Mode ─────────────────────────────────────────────────────
if mode == "Single Product":
    st.header("Generate Video & Blog for a Single Product")
    title       = st.text_input("Product Title")
    description = st.text_area("Product Description", height=150)
    uploaded_images = st.file_uploader(
        "Upload Product Images (PNG/JPG)",
        type=["png","jpg","jpeg"], accept_multiple_files=True
    )

    if st.button("Generate"):
        if not all([title, description, uploaded_images]):
            st.error("Please enter title, description, and images.")
        else:
            slug = slugify(title)
            with temp_workspace() as tmpdir:
                # save images
                image_urls = []
                for up in uploaded_images:
                    p = os.path.join(tmpdir, up.name)
                    with open(p, 'wb') as f: f.write(up.getbuffer())
                    image_urls.append(p)

                svc_cfg = ServiceConfig(
                    csv_file='',
                    images_json='',
                    audio_folder=tmpdir,
                    fonts_zip_path=fonts_folder,
                    logo_path=logo_path,
                    output_base_folder=tmpdir,
                )

                result = generate_for_single(
                    cfg=svc_cfg,
                    listing_id=None,
                    product_id=None,
                    title=title,
                    description=description,
                    image_urls=image_urls,
                )

                st.subheader(title)
                st.video(result.video_path)
                st.markdown("**Blog Content**")
                st.write(open(result.blog_file,'r',encoding='utf-8').read())

                # upload
                prod_f = drive_db.find_or_create_folder(slug, parent_id=outputs_id)
                try:
                    for path in [result.video_path, result.title_file, result.blog_file]:
                        mime = 'video/mp4' if path.endswith('.mp4') else 'text/plain'
                        drive_db.upload_file(
                            name=os.path.basename(path),
                            data=open(path,'rb').read(),
                            mime_type=mime,
                            parent_id=prod_f
                        )
                except Exception as e:
                    st.warning(f"⚠️ Failed to upload to Database: {e}")

# ─── Batch CSV Mode ──────────────────────────────────────────────────────────
else:
    st.header("Generate Video & Blog for a Batch of Products")
    up_csv  = st.file_uploader("Upload Products CSV", type="csv")
    up_json = st.file_uploader("Upload Images JSON", type="json")

    if st.button("Run Batch"):
        if not all([up_csv, up_json]):
            st.error("Please upload both CSV and JSON.")
        else:
            with temp_workspace() as master_tmp:
                csv_path  = os.path.join(master_tmp, up_csv.name)
                json_path = os.path.join(master_tmp, up_json.name)
                open(csv_path,'wb').write(up_csv.getbuffer())
                open(json_path,'wb').write(up_json.getbuffer())
                images_data = json.load(open(json_path))

                svc_cfg = ServiceConfig(
                    csv_file=csv_path,
                    images_json=json_path,
                    audio_folder=master_tmp,
                    fonts_zip_path=fonts_folder,
                    logo_path=logo_path,
                    output_base_folder=master_tmp,
                )

                generate_batch_from_csv(cfg=svc_cfg, images_data=images_data)

                for sub in os.listdir(master_tmp):
                    subdir = os.path.join(master_tmp, sub)
                    if not os.path.isdir(subdir): continue
                    st.subheader(f"Results for {sub}")
                    vid  = os.path.join(subdir, f"{sub}.mp4")
                    blog = os.path.join(subdir, f"{sub}_blog.txt")
                    if os.path.exists(vid):  st.video(vid)
                    if os.path.exists(blog): st.write(open(blog,'r').read())
                    prod_f = drive_db.find_or_create_folder(sub, parent_id=outputs_id)
                    try:
                        for path in glob.glob(os.path.join(subdir,'*')):
                            if path.lower().endswith(('.mp4','.txt')):
                                mime = 'video/mp4' if path.endswith('.mp4') else 'text/plain'
                                drive_db.upload_file(
                                    name=os.path.basename(path),
                                    data=open(path,'rb').read(),
                                    mime_type=mime,
                                    parent_id=prod_f
                                )
                    except Exception as e:
                        st.warning(f"⚠️ Failed to upload to Database: {e}")
