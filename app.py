import os
import requests
from requests.models import Response

# Monkey-patch requests.get to support local files
_orig_get = requests.get
def _get_or_file(path, *args, **kwargs):
    if os.path.isfile(path):
        r = Response()
        r.status_code = 200
        r._content = open(path, "rb").read()
        return r
    return _orig_get(path, *args, **kwargs)
requests.get = _get_or_file

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
    upload_videos_streamlit,
)

# Page Config & Authentication
st.set_page_config(page_title="AI Video Generator", layout="wide")
st.title("📹 AI Video Generator")

# Load Secrets and set OpenAI key
openai_api_key = st.secrets["OPENAI_API_KEY"]
drive_folder_id = st.secrets["DRIVE_FOLDER_ID"]
os.environ["OPENAI_API_KEY"] = openai_api_key
openai.api_key = openai_api_key

drive_db.DRIVE_FOLDER_ID = drive_folder_id

# Prepare Drive subfolders
def get_folder(name):
    return drive_db.find_or_create_folder(name, parent_id=drive_folder_id)
inputs_id = get_folder("inputs")
outputs_id = get_folder("outputs")
fonts_id = get_folder("fonts")
logo_id = get_folder("logo")

@st.cache_data
def list_drive(mime_filter, parent_id):
    return drive_db.list_files(mime_filter=mime_filter, parent_id=parent_id)

# Preload fonts and logo (omitted for brevity, assume existing code above)
# ...

mode = st.sidebar.radio("Mode", ["Single Product", "Batch from CSV"])

if mode == "Single Product":
    # Existing single-product logic unchanged
    pass  # (omitted)
else:
    st.header("Batch Video & Blog Generation from CSV")

    # --- Modified Batch: Use file uploaders instead of Drive lists ---
    uploaded_csv = st.file_uploader("Upload Products CSV", type="csv")
    uploaded_json = st.file_uploader("Upload Images JSON (optional)", type="json")

    if st.button("Run Batch"):
        if not uploaded_csv:
            st.error("Please upload a Products CSV to proceed.")
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Save and load CSV
                csv_path = os.path.join(tmpdir, uploaded_csv.name)
                with open(csv_path, "wb") as f:
                    f.write(uploaded_csv.getbuffer())
                vgs.csv_file = csv_path
                df = pd.read_csv(csv_path)
                st.write("DEBUG: CSV head", df.head())

                # Save and load JSON
                images_data = {}
                if uploaded_json:
                    json_path = os.path.join(tmpdir, uploaded_json.name)
                    with open(json_path, "wb") as f:
                        f.write(uploaded_json.getbuffer())
                    vgs.images_json = json_path
                    images_data = json.load(open(json_path))
                    st.write("DEBUG: images_data keys", list(images_data.keys()))

                # Patch audio and output
                vgs.audio_folder = tmpdir
                vgs.output_folder = tmpdir
                st.write("DEBUG: audio_folder contents", os.listdir(vgs.audio_folder))

                # Run batch generation
                try:
                    create_videos_and_blogs_from_csv(
                        input_csv_file=vgs.csv_file,
                        images_data=images_data,
                        products_df=df,
                        output_base_folder=tmpdir,
                    )
                except Exception as e:
                    st.error(f"❌ Batch generation failed: {e}")
                    raise

                # Upload results
                results = upload_videos_streamlit(
                    tmpdir,
                    drive_db.upload_file,
                    lambda blog, url: blog + f"\n\nVideo at {url}"
                )
                for name, ok, msg in results:
                    st.write(f"{name}: {'✅' if ok else '❌'} {msg}")
