
# EComListing-AI: AI-Powered Multimedia Content Generator for eCommerce

EComListing-AI helps eCommerce businesses create **engaging multimedia content** using AI — from a single product or entire catalogs.  

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

### 🔹 Persistent Session State
- Keeps your selections across mode switches
- Resets mode-specific fields as needed

### 🔹 Google Drive Integration
- Upload all output files to a defined folder in your Google Drive
- Per-product folders keep results organized
- Supports:
  - 🔐 OAuth with refresh token (user account)
  - 🤖 Service Account (Shared Drive / server-to-server)

---

## 🔧 Getting Started

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

```toml
# Required
OPENAI_API_KEY  = "sk-..."

DRIVE_FOLDER_ID = "your-google-drive-folder-id"

# Option A: OAuth (preferred for most users)
[oauth_manual]
client_id     = "..."
client_secret = "..."
refresh_token = "..."

# Option B: Service Account
[drive_service_account]
type                          = "service_account"
project_id                    = "..."
private_key_id                = "..."
private_key                   = "..."
client_email                  = "..."
client_id                     = "..."
auth_uri                      = "https://accounts.google.com/o/oauth2/auth"
token_uri                     = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url   = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url          = "https://www.googleapis.com/robot/v1/metadata/x509/..."
```

### 4. Run the app

```bash
streamlit run app.py
```

---

## 🖥️ Usage

### ▶️ Single Product Workflow
1. Select **Single Product Mode**
2. Fill in **Title** and **Description**
3. Upload images
4. Click **Generate**
5. Preview results, then hit **Continue** to save

### 📊 Batch Product Workflow
1. Select **Batch Mode**
2. Upload a CSV file with required columns:
   - `Listing Id`, `Product Id`, `Title`, `Description`
3. Upload **Images JSON** (if CSV doesn’t contain image URLs)
4. Click **Run Batch**
5. Outputs will be previewed and saved for each product

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
│
├── app.py                    ← Streamlit UI logic
├── video_generation_service.py  ← Core logic for blog & video generation
├── drive_db.py               ← Google Drive API wrapper
├── utils.py                  ← Utility functions
├── .streamlit/
│   └── secrets.toml          ← API keys (DO NOT COMMIT)
├── requirements.txt
└── README.md
```

---

## 🧑‍💻 Contributing

1. Fork the repo  
2. Create your feature branch: `git checkout -b feat/your-feature`  
3. Commit your changes: `git commit -m 'feat: added new feature'`  
4. Push to branch: `git push origin feat/your-feature`  
5. Open a Pull Request 🚀

---

## 📄 License

This project is licensed under the [MIT License](./LICENSE)  
© 2025 TrustClarity / EComListing-AI Team

---
