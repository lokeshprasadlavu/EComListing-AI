import os
import json
import streamlit as st
import pandas as pd
import video_generation_service as vgs
from video_generation_service import create_video_for_product, create_videos_and_blogs_from_csv

# Load and expand config
CONFIG_PATH = "config.json"
@st.cache_data

def load_config(path):
    raw = open(path, 'r').read()
    expanded = os.path.expandvars(raw)
    return json.loads(expanded)

cfg = load_config(CONFIG_PATH)

# Ensure environment
os.environ.setdefault("OPENAI_API_KEY", cfg.get("openai_api_key", ""))

# Patch module-level constants
vgs.CSV_FILE      = cfg.get("csv_products")
vgs.OUTPUT_FOLDER = cfg.get("output_folder")
vgs.AUDIO_FOLDER  = cfg.get("audio_folder")
vgs.FONTS_FOLDER  = cfg.get("fonts_folder")
vgs.POPPINS_ZIP   = cfg.get("poppins_zip")
vgs.LOGO_PATH     = cfg.get("logo_path")
vgs.IMAGES_JSON   = cfg.get("images_json")

# Streamlit UI
st.set_page_config(page_title="AI Video Generator", layout="wide")
st.title("📹 AI Video Generator")

mode = st.sidebar.radio("Select mode", ["Single Product", "Batch from CSV"])

if mode == "Single Product":
    st.header("Single Product Video")
    listing_id  = st.text_input("Listing ID")
    product_id  = st.text_input("Product ID")
    title       = st.text_input("Product Title")
    description = st.text_area("Product Description", height=150)
    uploaded_images = st.file_uploader(
        "Upload product images", type=["png","jpg","jpeg"], accept_multiple_files=True
    )
    if st.button("Generate Video"):
        if not (listing_id and product_id and title and description and uploaded_images):
            st.error("All fields and at least one image are required.")
        else:
            temp_dir = os.path.join("./temp_uploads")
            os.makedirs(temp_dir, exist_ok=True)
            images = []
            for f in uploaded_images:
                path = os.path.join(temp_dir, f.name)
                with open(path, "wb") as out:
                    out.write(f.getbuffer())
                images.append({"imageURL": path})

            os.makedirs(cfg["output_folder"], exist_ok=True)
            st.info("Generating video...")
            try:
                create_video_for_product(
                    listing_id,
                    product_id,
                    title,
                    description,
                    images,
                    cfg["output_folder"]
                )
                video_path = os.path.join(cfg["output_folder"], f"{listing_id}_{product_id}.mp4")
                if os.path.exists(video_path):
                    st.success("Video generated!")
                    st.video(video_path)
                else:
                    st.error("Video not found after generation.")
            except Exception as e:
                st.error(f"Error: {e}")

else:
    st.header("Batch Generation from CSV")
    csv_file = st.file_uploader("Upload products CSV", type=["csv"])
    images_json = st.file_uploader("Upload images JSON (optional)", type=["json"])
    if st.button("Run Batch"): 
        if not csv_file:
            st.error("Please upload a CSV to proceed.")
        else:
            # Save uploads
            csv_path = os.path.join("./temp_uploads", csv_file.name)
            os.makedirs("./temp_uploads", exist_ok=True)
            with open(csv_path, "wb") as out:
                out.write(csv_file.getbuffer())
            cfg["csv_products"] = csv_path

            images_data = {}
            if images_json:
                json_path = os.path.join("./temp_uploads", images_json.name)
                with open(json_path, "wb") as out:
                    out.write(images_json.getbuffer())
                images_data = json.load(open(json_path))
            
            df = pd.read_csv(cfg["csv_products"])
            os.makedirs(cfg["output_folder"], exist_ok=True)
            st.info("Running batch generation...")
            try:
                create_videos_and_blogs_from_csv(
                    input_csv_file     = cfg["csv_products"],
                    images_data        = images_data,
                    products_df        = df,
                    output_base_folder = cfg["output_folder"]
                )
                st.success("Batch run complete! Videos are in the output folder.")
            except Exception as e:
                st.error(f"Batch error: {e}")
