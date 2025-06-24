# EComListing-AI

An AI-powered multimedia content generation service for eCommerce product listings.  
Turn your product catalog (CSV + JSON of image URLs) or single product inputs into polished videos, AI-written blogs, and text snippets—automatically uploaded to Google Drive (and soon YouTube).

---

## 🚀 Features

- **Generate Video for a Single Product**  
  - Streamlit UI to enter Title, Description, and upload images.  
  - Generates a product video via your AI backend.  
  - Previews the video in-page and uploads video + text files to DB.

- **Generate Video & Blog for a Batch of Products**  
  - Upload a products CSV and images JSON.  
  - Loops through each row, generates video + blog, previews each, and uploads per-item outputs.  
  - Maintains a clean per-product folder so each run is isolated.

- **Google Drive Integration**  
  - Upload everything under a single “outputs” folder in your Drive.  
  - Supports two auth modes:
    1. **OAuth Manual-Token** (zero-touch after initial setup)  
    2. **Service Account** (for Shared Drive or server-to-server workflows)

- **Zero-Touch Deployment**  
  - Once your refresh token or service-account secret is in place, repeated deploys auto-refresh and never prompt.

---

## 📂 Repo Structure

```
EComListing-AI/
│
├── .streamlit/
│   └── secrets.toml      ← your API keys & OAuth tokens (DO NOT COMMIT)
│
├── app.py                ← Streamlit frontend & UI logic
├── video_generation_service.py  
│                         ← core AI video/blog generation code
├── drive_db.py           ← Google Drive auth & upload/download helpers
├── requirements.txt      ← Python dependencies
└── README.md             ← this file
```

---

## ⚙️ Getting Started

1. **Clone the repo**  
   ```bash
   git clone https://github.com/your-org/EComListing-AI.git
   cd EComListing-AI
   ```

2. **Install dependencies**  
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure your secrets**  
   Create a file at `.streamlit/secrets.toml` with the following structure (do **not** commit it):

   ```toml
   # Your OpenAI API key for text/video prompts
   OPENAI_API_KEY  = "sk-..."

   # The Drive folder under which “inputs”/“outputs” live
   DRIVE_FOLDER_ID = "your-google-drive-folder-id"

   # Option A: Manual OAuth (zero-touch after initial Playground step)
   [oauth_manual]
   client_id     = "YOUR_WEB_CLIENT_ID"
   client_secret = "YOUR_WEB_CLIENT_SECRET"
   refresh_token = "1//0xYOUR_REFRESH_TOKEN_FROM_PLAYGROUND"

   # Option B: Service Account (for server-to-server / Shared Drive)
   [drive_service_account]
   type                    = "service_account"
   project_id              = "..."
   private_key_id          = "..."
   private_key             = "-----BEGIN PRIVATE KEY-----
...
-----END PRIVATE KEY-----
"
   client_email            = "..."
   client_id               = "..."
   auth_uri                = "https://accounts.google.com/o/oauth2/auth"
   token_uri               = "https://oauth2.googleapis.com/token"
   auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
   client_x509_cert_url    = "https://www.googleapis.com/robot/v1/metadata/x509/..."
   ```

4. **Run the Streamlit app**  
   ```bash
   streamlit run app.py
   ```

---

## 📖 Usage

### Generate Video for a Single Product
1. Select **Generate Video for a Single Product** in the sidebar.  
2. Fill in **Title**, **Description**.  
3. Upload one or more product images.  
4. Click **Generate Video**.  
5. Preview the video inline; it will also be uploaded to Drive.

### Generate Video & Blog for a Batch of Products
1. Select **Generate Video & Blog for a Batch of Products**.  
2. Upload your **Products CSV** (must include columns `Listing Id`, `Product Id`, and `Title`).  
3. Upload your **Images JSON** (list of `{ listingId, productId, images: [...] }` entries).  
4. Click **Run Batch**.  
5. For each product:  
   - The app generates video + blog text.  
   - Previews the video and renders the blog in the UI.  
   - Uploads all outputs (`.mp4` + `.txt`) into a Drive folder named `{ListingId}_{ProductId}`.

---

## 🔜 Next Phases

1. **AI-Driven Image Generation**  
   - Integrate DALL·E / Stable Diffusion to let users generate images from prompts in the UI.  
   - Provide a gallery & selection interface.

2. **YouTube Upload**  
   - Add YouTube Data API support for direct publish of generated videos.  
   - Offer title, description, tags fields and show upload progress + final URL.

3. **Dashboard & Analytics**  
   - Track how many videos/blogs generated, storage usage, and API quotas.  
   - Provide a simple analytics dashboard within Streamlit.

---

## 🤝 Contributing

1. Fork the repo  
2. Create a new branch (`git checkout -b feature/YourFeature`)  
3. Make your changes & add tests/docs  
4. Submit a pull request  

---
