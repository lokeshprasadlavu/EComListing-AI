
# EComListing-AI: AI-Powered Multimedia Content Generator for eCommerce

EComListing-AI helps eCommerce businesses create **engaging multimedia content** using AI, for a single product or entire catalogs.  

✨ Generate **Videos**, 📝 **Blogs**, and soon, 🖼️ **AI-generated Images**, with zero design or editing effort.  
📦 Outputs are automatically uploaded to **Google Drive** — with **YouTube** integration coming soon!

---

## 🚀 Features

### 🔹 Single Product Mode
- Enter product **Title** and **Description**
- Upload product **Images** (PNG/JPG)
- Generate:
  - 🎞️ Video
  - 📝 Blog content
- Preview video and blog directly in the app
- Outputs saved automatically to your Google Drive

### 🔹 Batch Product Mode
- Upload a **CSV** of product data (title, description, IDs)
- Optionally upload a **JSON** of image URLs (if not included in CSV)
- For each product:
  - Generates video and blog using AI
  - Renders outputs in the UI
  - Uploads all files to Drive under structured folders

### 🔹 Google Drive Integration
- Upload all output files to a defined folder in your Google Drive
- Per-product folders keep results organized
- Supports:
  - 🔐 OAuth with refresh token (user account)
  - 🤖 Service Account (Shared Drive / server-to-server)

---

## 🔧 Getting Started

## Frontend (Streamlit)

### 1. Clone the repo

```bash
git clone https://github.com/your-org/EComListing-AI.git
cd EComListing-AI
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Add secrets

Create `.streamlit/secrets.toml`:

In `frontend/.streamlit/secrets.toml`:

```toml
[api]
backend_url = "https://<your-railway-backend>.up.railway.app/generate"
lottie_url = "https://assets8.lottiefiles.com/.../animation.json"

DRIVE_FOLDER_ID = "your-root-folder-id"

[oauth_manual]
client_id = "..."
client_secret = "..."
refresh_token = "..."

# OR

[drive_service_account]
type = "service_account"
project_id = "..."
private_key = "..."
client_email = "..."
```

### 4. Run the app

```bash
streamlit run app.py
```

---
## 🚂 Backend (FastAPI / Flask on Railway)

### ▶️ Deploy to Railway

1. Go to [Railway](https://railway.app/)
2. Create a new project, deploy `backend/`
3. Set environment variables:
   - `OPENAI_API_KEY`
   - Any model-specific or Drive settings

4. Confirm `/generate` route is accessible and returns output

---

## 🔗 Shared Package

`frontend` and `backend` import modules from `shared/` like:

```python
from shared.auth import init_drive_service
from shared.utils import slugify
```

Make sure Python paths are set correctly. In local/dev, this is handled via:

```python
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
```

---

## 🖥️ Usage

### ▶️ Single Product Workflow
1. Select **Single Product Mode**
2. Fill in **Title** and **Description**
3. Upload images
4. Click **Generate**
5. Preview results

### 📊 Batch Product Workflow
1. Select **Batch Mode**
2. Upload a CSV file with required columns:
   - `Listing Id`, `Product Id`, `Title`, `Description`
3. Upload **Images JSON** (if CSV doesn’t contain image URLs)
4. Click **Run Batch**
5. Outputs will be previewed

---

## 🔮 Coming Soon

- 🧠 **AI Image Generation**
  - Generate product images using DALL·E / Stable Diffusion
  - Let users add missing or stylized product visuals

- 📺 **YouTube Upload Support**
  - Connect to your channel
  - Auto-publish generated videos with metadata

- 📊 **Dashboard & Analytics**
  - Track generation stats, video/blog count, storage, and API usage

---

## 📂 Project Structure
```
EComListing-AI/
├── frontend/           # Streamlit UI app
│   └── requirements.txt         
│   └── app.py
│   └── .streamlit/
│       └── secrets.toml  # (DO NOT COMMIT)
│
├── backend/             # FastAPI (or Flask) backend service
│   └── main.py
│   └── video_generation_service.py # Core logic for blog & video generation
│   └── Dockerfile
│   └── requirements.txt
│
├── shared/  # Reusable functions
│   └── config.py
│   └── auth.py
│   └── drive_db.py
│   └── utils.py
│
└── README.md
```

---
## 🧑‍💻 Contributing

Pull requests are welcome! Fork the repo and open a PR from a feature branch.

---
