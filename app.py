import os, json, tempfile
import streamlit as st
import pandas as pd
import video_generation_service as vgs
from video_generation_service import create_video_for_product, create_videos_and_blogs_from_csv
import drive_db

st.set_page_config(page_title="AI Video Generator", layout="wide")
st.title("📹 AI Video Generator")

# ── Authenticate & set Drive root ─────────────────
OPENAI_API_KEY  = st.secrets["OPENAI_API_KEY"]
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
drive_db.DRIVE_FOLDER_ID = DRIVE_FOLDER_ID

# Create or get sub-folders
INPUTS_ID   = drive_db.find_or_create_folder("inputs")
OUTPUTS_ID  = drive_db.find_or_create_folder("outputs")
FONTS_ID    = drive_db.find_or_create_folder("fonts")
LOGO_ID     = drive_db.find_or_create_folder("logo")

@st.cache_data
def list_drive(mime, parent):
    return drive_db.list_files(mime_filter=mime, parent_id=parent)

mode = st.sidebar.radio("Mode", ["Single Product", "Batch from CSV"])

if mode == "Single Product":
    st.header("Single Product Video Generation")
    lid = st.text_input("Listing ID"); pid = st.text_input("Product ID")
    title = st.text_input("Product Title"); desc = st.text_area("Description", height=150)

    # images from inputs
    imgs = list_drive("image/", INPUTS_ID)
    choices = [f["name"] for f in imgs]
    selected = st.multiselect("Select images", choices)

    if st.button("Generate Video"):
        if not all([lid, pid, title, desc, selected]):
            st.error("Fill all fields + pick ≥1 image")
        else:
            with tempfile.TemporaryDirectory() as tmp:
                # download selected
                images=[]
                for name in selected:
                    meta = next(f for f in imgs if f["name"]==name)
                    buf = drive_db.download_file(meta["id"])
                    p = os.path.join(tmp, name)
                    open(p,"wb").write(buf.read())
                    images.append({"imageURL":p})

                # patch globals
                vgs.AUDIO_FOLDER=tmp; vgs.FONTS_FOLDER=tmp; vgs.LOGO_PATH=None

                # generate locally
                create_video_for_product(lid, pid, title, desc, images, tmp)

                # upload result
                fname = f"{lid}_{pid}.mp4"
                outpath = os.path.join(tmp, fname)
                if os.path.exists(outpath):
                    data = open(outpath,"rb").read()
                    drive_db.upload_file(fname, data, "video/mp4", parent_id=OUTPUTS_ID)
                    st.success(f"Uploaded {fname}")
                    st.video(outpath)
                else:
                    st.error("Generation failed")

else:
    st.header("Batch from CSV")
    csvs = list_drive("text/csv", INPUTS_ID)
    csv_name = st.selectbox("Choose CSV", [f["name"] for f in csvs])
    jsons = list_drive("application/json", INPUTS_ID)
    json_name = st.selectbox("Choose JSON (opt)", ["(none)"]+[f["name"] for f in jsons])

    if st.button("Run Batch"):
        with tempfile.TemporaryDirectory() as tmp:
            # download CSV
            meta = next(f for f in csvs if f["name"]==csv_name)
            buf = drive_db.download_file(meta["id"])
            csvp = os.path.join(tmp, csv_name)
            open(csvp,"wb").write(buf.read())
            df = pd.read_csv(csvp)

            # images json
            images_data={}
            if json_name!="(none)":
                jm = next(f for f in jsons if f["name"]==json_name)
                bj = drive_db.download_file(jm["id"])
                jp = os.path.join(tmp,json_name)
                open(jp,"wb").write(bj.read())
                images_data = json.load(open(jp))

            # patch
            vgs.AUDIO_FOLDER=tmp; vgs.FONTS_FOLDER=tmp; vgs.LOGO_PATH=None

            # run
            create_videos_and_blogs_from_csv(
                input_csv_file=csvp,
                images_data=images_data,
                products_df=df,
                output_base_folder=tmp
            )

            # upload movies
            ups=[]
            for f in os.listdir(tmp):
                if f.lower().endswith(".mp4"):
                    data=open(os.path.join(tmp,f),"rb").read()
                    drive_db.upload_file(f,data,"video/mp4",parent_id=OUTPUTS_ID)
                    ups.append(f)
            if ups:
                st.success(f"Uploaded {len(ups)} videos")
            else:
                st.error("No videos generated")
