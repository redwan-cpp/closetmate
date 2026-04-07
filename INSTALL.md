# 🚀 ClosetMate — Installation & Setup Guide

This guide walks you through cloning, configuring, and running the full ClosetMate stack from scratch — the AI backend and the React Native mobile app.

---

## 📋 Prerequisites

Make sure the following are installed on your machine before you begin:

| Tool | Minimum Version | Download |
|---|---|---|
| **Git** | any | https://git-scm.com |
| **Python** | 3.10+ | https://www.python.org/downloads/ |
| **Node.js** | 18+ | https://nodejs.org |
| **npm** | 9+ | (comes with Node.js) |
| **Expo Go** (phone app) | latest | App Store / Google Play |

You will also need:
- A **Gemini API key** → https://aistudio.google.com/app/apikey
- An **OpenAI API key** → https://platform.openai.com/api-keys

---

## 1. Clone the Repository

```bash
git clone https://github.com/redwan-cpp/closetmate.git
cd closetmate
```

---

## 2. Backend Setup — `closetmate-ai/`

The backend is a **Python FastAPI** server that handles AI image processing and outfit recommendations.

### Step 1 — Enter the backend directory

```bash
cd closetmate-ai
```

### Step 2 — Create a Python virtual environment

```bash
# Windows
python -m venv venv

# macOS / Linux
python3 -m venv venv
```

### Step 3 — Activate the virtual environment

```bash
# Windows (PowerShell)
venv\Scripts\Activate.ps1

# Windows (Command Prompt)
venv\Scripts\activate.bat

# macOS / Linux
source venv/bin/activate
```

You should see `(venv)` at the start of your terminal prompt.

### Step 4 — Install Python dependencies

```bash
pip install -r requirements.txt
```

> ⏳ This may take a few minutes the first time — it installs AI/image libraries like `rembg`, `opencv`, and `onnxruntime`.

### Step 5 — Create your `.env` file

```bash
# Windows (PowerShell)
Copy-Item .env.example .env

# macOS / Linux
cp .env.example .env
```

Open the newly created `.env` file and replace the placeholder values with your real API keys:

```env
GEMINI_API_KEY=your_gemini_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
```

### Step 6 — Run the backend server

**Option A — Double-click `start.bat`** (Windows only, easiest):

> Just double-click `closetmate-ai/start.bat` in File Explorer. A terminal window will open and the server will start automatically.

**Option B — Run manually in the terminal:**

```bash
# Make sure the venv is still activated, then:
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

✅ The backend is running when you see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

You can open **http://localhost:8000/docs** in your browser to explore the API.

---

## 3. Frontend Setup — `closetmate/`

The mobile app is built with **React Native + Expo**. Open a **new terminal window** (keep the backend running).

### Step 1 — Enter the frontend directory

```bash
# From project root:
cd closetmate
```

### Step 2 — Install JavaScript dependencies

```bash
npm install
```

### Step 3 — Configure the backend URL

Open `closetmate/src/api/ai.ts` and set the `BASE_URL` to your machine's **local IP address**:

```ts
// Find your local IP:
//   Windows: run `ipconfig` → look for IPv4 Address (e.g. 192.168.1.5)
//   macOS/Linux: run `ifconfig` or `ip addr`

const BASE_URL = "http://192.168.1.5:8000";  // ← replace with your IP
```

> ⚠️ Do NOT use `localhost` or `127.0.0.1` here — your phone can't reach those from a physical device. You must use your PC's actual LAN IP.

### Step 4 — Start the Expo development server

```bash
npx expo start
```

A **QR code** will appear in the terminal.

### Step 5 — Open the app on your phone

1. Make sure your phone and PC are on the **same Wi-Fi network**.
2. Open the **Expo Go** app on your phone.
3. Scan the QR code shown in the terminal.

The app will load on your device. 🎉

---

## 4. Running Both Services Together

You need **two terminal windows** running simultaneously:

| Terminal | Command | Directory |
|---|---|---|
| ① Backend | `uvicorn main:app --host 0.0.0.0 --port 8000 --reload` | `closetmate-ai/` |
| ② Frontend | `npx expo start` | `closetmate/` |

---

## 5. Troubleshooting

### ❌ Backend: `ModuleNotFoundError`
Make sure your virtual environment is **activated** before running:
```bash
venv\Scripts\activate.bat    # Windows
source venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
```

### ❌ Backend: `GEMINI_API_KEY not set` or similar
Make sure your `.env` file exists in `closetmate-ai/` and contains valid keys.

### ❌ App: "Network request failed" or can't reach the backend
- Check that the backend is running (visit http://localhost:8000/docs in your browser).
- Verify the IP in `src/api/ai.ts` matches your machine's **current** local IP.
- Both devices must be on the **same Wi-Fi network**.
- Temporarily disable your firewall or add an allow rule for port `8000`.

### ❌ App: `npm install` fails
- Make sure you are **inside the `closetmate/` folder**, not the root.
- Try deleting `node_modules/` and running `npm install` again.

### ❌ Expo: QR code doesn't work
Try switching to **tunnel mode**:
```bash
npx expo start --tunnel
```
This requires the `@expo/ngrok` package:
```bash
npm install -g @expo/ngrok
```

---

## 6. Project Structure (Quick Reference)

```
closetmate/                  ← repo root
├── closetmate/              ← React Native (Expo) mobile app
│   ├── app/                 ← Expo Router screens
│   ├── components/          ← Reusable UI components
│   ├── src/api/ai.ts        ← API client (set your backend IP here)
│   └── package.json
│
└── closetmate-ai/           ← Python FastAPI AI backend
    ├── main.py              ← FastAPI app entry point
    ├── routers/             ← API route handlers
    ├── services/            ← AI/image processing logic
    ├── requirements.txt     ← Python dependencies
    ├── .env.example         ← Copy to .env and add your keys
    └── start.bat            ← One-click start (Windows)
```

---

## 7. API Keys — Where to Get Them

| Key | Purpose | Link |
|---|---|---|
| `GEMINI_API_KEY` | Outfit recommendations & style analysis | https://aistudio.google.com/app/apikey |
| `OPENAI_API_KEY` | Vision analysis for clothing metadata | https://platform.openai.com/api-keys |

Both services have **free tiers** sufficient for development use.

---

## 📄 License

MIT
