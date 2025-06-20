import os, uuid, json, pandas as pd, time
import streamlit as st
from PIL import Image, ImageDraw, ImageFont
from video_helpers        import (
    ensure_clean_dirs,
    clean_text,
    split_text_into_slides,
)
from transcript           import get_video_transcript
from audio_helpers        import create_audio_with_gtts
from video_gen            import create_video_for_product
from batch_pipeline       import create_videos_and_blogs_from_csv, upload_videos_streamlit
from youtube_uploader     import upload_video_to_youtube

# ─── Config & Setup ───────────────────────────────────────────────
st.set_page_config(page_title="TrustClarity AI Video", layout="wide")
ensure_clean_dirs("output", "audio", "fonts")

# Streamlit Sidebar
mode = st.sidebar.radio("Mode", ["Single", "Batch CSV", "Batch Upload"])
st.sidebar.markdown("---")

# ─── Single-Video Mode ─────────────────────────────────────────────
if mode == "Single":
    st.header("Single Product Video")
    listing_id = st.text_input("Listing ID")
    product_id = st.text_input("Product ID")
    title      = st.text_input("Title")
    desc       = st.text_area("Description")
    imgs_json  = st.file_uploader("Image metadata JSON", accept_multiple_files=True, type="json")

    if st.button("Generate & Preview"):
        if not all([listing_id, product_id, title, desc, imgs_json]):
            st.error("Fill in all fields & upload at least one JSON.")
        else:
            images = [json.loads(f.read()) for f in imgs_json]
            out_dir = "output"
            create_video_for_product(
                listing_id, product_id, title, desc, images, out_dir
            )
            out_file = f"{out_dir}/{listing_id}_{product_id}.mp4"
            st.video(out_file)

# ─── Batch CSV Mode ───────────────────────────────────────────────
elif mode == "Batch CSV":
    st.header("Batch Videos & Blogs from CSV")
    csv_file     = st.file_uploader("Products CSV", type="csv")
    json_file    = st.file_uploader("Images JSON", type="json")
    master_csv   = st.file_uploader("Master Products CSV", type="csv")

    if st.button("Run Batch"):
        if not (csv_file and json_file and master_csv):
            st.error("Upload all three files.")
        else:
            tmp_csv  = "/tmp/products.csv"; open(tmp_csv,  "wb").write(csv_file.getbuffer())
            tmp_json = "/tmp/images.json";  open(tmp_json, "wb").write(json_file.getbuffer())
            tmp_master = "/tmp/master.csv"; open(tmp_master,"wb").write(master_csv.getbuffer())

            images_data = json.loads(open(tmp_json).read())
            products_df = pd.read_csv(tmp_master)
            create_videos_and_blogs_from_csv(tmp_csv, images_data, products_df, "output")
            st.success("Batch complete! Check `output/` folder.")

# ─── Batch Upload Mode ─────────────────────────────────────────────
else:
    st.header("Batch Upload to YouTube")
    if st.button("Upload All Videos"):
        results = upload_videos_streamlit("output")
        for name, success, info in results:
            if success:
                st.success(f"{name} → {info}")
            else:
                st.error(f"{name} failed: {info}")
