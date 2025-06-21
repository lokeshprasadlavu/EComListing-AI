import os
import tempfile
import streamlit as st
import pandas as pd
import video_generation_service as vgs
from video_generation_service import create_video_for_product, create_videos_and_blogs_from_csv
import drive_db
import json

# Streamlit page config
st.set_page_config(page_title="AI Video Generator (Drive-Backed)", layout="wide")
st.title("📹 AI Video Generator")

# ---- Configuration & Auth ----
# Load secrets from Streamlit
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY")
DRIVE_FOLDER_ID = st.secrets.get("DRIVE_FOLDER_ID")
# Export for OpenAI
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
# Configure drive_db
drive_db.DRIVE_FOLDER_ID = DRIVE_FOLDER_ID

# ---- Helper: list drive files by type ----
@st.cache_data
def get_drive_files(mime_filter=None):
    files = drive_db.list_files()
    if mime_filter:
        return [f for f in files if f.get("mimeType", "").startswith(mime_filter)]
    return files

# ---- Select mode ----
mode = st.sidebar.radio("Mode", ["Single Product", "Batch from CSV"])

if mode == "Single Product":
    st.header("Single Product Video Generation")
    # Text inputs
    listing_id = st.text_input("Listing ID")
    product_id = st.text_input("Product ID")
    title = st.text_input("Product Title")
    description = st.text_area("Product Description", height=150)

    # Select images from Drive
    image_files = get_drive_files(mime_filter="image/")
    image_names = [f["name"] for f in image_files]
    selected = st.multiselect("Select product images", image_names)

    if st.button("Generate Video"):
        if not (listing_id and product_id and title and description and selected):
            st.error("Please fill all fields and select at least one image.")
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                images = []
                # Download selected images
                for name in selected:
                    file_meta = next(f for f in image_files if f["name"] == name)
                    buf = drive_db.download_file(file_meta["id"])
                    img_path = os.path.join(tmpdir, name)
                    with open(img_path, "wb") as f:
                        f.write(buf.read())
                    images.append({"imageURL": img_path})

                # Call backend
                output_local = tmpdir
                vgs.AUDIO_FOLDER = tmpdir
                vgs.FONTS_FOLDER = tmpdir
                vgs.LOGO_PATH = None  # if unused

                create_video_for_product(
                    listing_id=listing_id,
                    product_id=product_id,
                    title=title,
                    text=description,
                    images=images,
                    output_folder=output_local
                )

                # Upload and preview
                video_name = f"{listing_id}_{product_id}.mp4"
                video_path = os.path.join(output_local, video_name)
                if os.path.exists(video_path):
                    # Upload back to Drive
                    with open(video_path, "rb") as vf:
                        data = vf.read()
                    drive_db.upload_file(video_name, data, mime_type="video/mp4")
                    st.success(f"Video generated & uploaded as {video_name}")
                    st.video(video_path)
                else:
                    st.error("Video generation failed.")

else:
    st.header("Batch Video & Blog Generation from CSV")
    # Select CSV from Drive
    csv_files = [f for f in get_drive_files() if f.get("mimeType")=="text/csv"]
    csv_choice = st.selectbox("Select Products CSV", [f["name"] for f in csv_files])
    json_files = [f for f in get_drive_files() if f.get("mimeType")=="application/json"]
    json_choice = st.selectbox("Select Images JSON (optional)", ["(none)"] + [f["name"] for f in json_files])

    if st.button("Run Batch"):
        # Download CSV
        csv_meta = next(f for f in csv_files if f["name"]==csv_choice)
        csv_buf = drive_db.download_file(csv_meta["id"])
        df = pd.read_csv(csv_buf)
        # Download JSON if provided
        images_data = {}
        if json_choice != "(none)":
            json_meta = next(f for f in json_files if f["name"]==json_choice)
            json_buf = drive_db.download_file(json_meta["id"])
            images_data = json.load(json_buf)

        # Prepare temp output folder
        with tempfile.TemporaryDirectory() as tmpout:
            vgs.AUDIO_FOLDER = tmpout
            vgs.FONTS_FOLDER = tmpout
            vgs.LOGO_PATH = None

            create_videos_and_blogs_from_csv(
                input_csv_file=csv_meta["name"],  # not used internally
                images_data=images_data,
                products_df=df,
                output_base_folder=tmpout
            )

            # Upload all generated videos back
            uploaded = []
            for fname in os.listdir(tmpout):
                if fname.endswith(".mp4"):
                    path = os.path.join(tmpout, fname)
                    with open(path, "rb") as vf:
                        data = vf.read()
                    drive_db.upload_file(fname, data, mime_type="video/mp4")
                    uploaded.append(fname)
            if uploaded:
                st.success(f"Uploaded {len(uploaded)} videos back to Drive.")
            else:
                st.error("No videos were generated.")
