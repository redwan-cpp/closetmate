# ClosetMate 

**ClosetMate** is an AI-powered smart wardrobe app built with React Native (Expo) and a Python FastAPI backend. It helps users manage their clothing, get AI-generated outfit suggestions, and add items to their closet by photographing them.

---

## 📁 Project Structure

```
Closetmate/
├── closetmate/          # React Native (Expo) mobile app
└── closetmate-ai/       # Python FastAPI AI backend
```

---

## 📱 Mobile App — `closetmate/`

### Features
- **Stylist** — Chat-based AI outfit suggestions with outfit cards
- **Closet** — Grid view of your wardrobe with category filters (Tops, Bottoms, Dresses, Footwear)
- **Camera Button** — Floating action button to capture or upload clothing items
- **Explore** — Discover outfit inspiration from the community with AI style insights
- **Profile** — Body shape, skin tone selector, worn history calendar, and AI style insights

### Tech Stack
| Tech | Purpose |
|---|---|
| Expo (React Native) | Cross-platform mobile framework |
| Expo Router | File-based navigation |
| Expo Image Picker | Camera & gallery access |
| Expo File System | Local file storage for styled images |
| Expo Haptics | Haptic feedback on tab press |
| TypeScript | Type safety |
| NativeWind | Utility-first styling |

### Getting Started

**Prerequisites:** Node.js, npm, Expo Go app on your phone

```bash
cd closetmate
npm install
npx expo start
```

Scan the QR code with **Expo Go** (iOS/Android) to run the app.

### App Structure

```
closetmate/
├── app/
│   ├── _layout.tsx              # Root stack navigator
│   ├── add-item.tsx             # Add item screen (camera + AI styling)
│   └── (tabs)/
│       ├── _layout.tsx          # Tab bar config + floating camera button
│       ├── stylist.tsx          # AI chat stylist screen
│       ├── closet.tsx           # Wardrobe grid screen
│       ├── explore.tsx          # Community explore feed
│       └── profile.tsx          # User profile screen
├── components/
│   ├── FloatingCameraButton.tsx # Center FAB with camera/library options
│   ├── ChatBubble.tsx           # Reusable chat bubble component
│   ├── ClothingCard.tsx         # Clothing item card for closet grid
│   ├── OutfitCard.tsx           # Full outfit suggestion card
│   ├── ExploreCard.tsx          # Explore feed card with overlay
│   ├── AIInsightCard.tsx        # AI style tip card
│   ├── FilterChip.tsx           # Category filter pill button
│   └── ui/                      # TabBarBackground, IconSymbol, Collapsible
├── constants/
│   ├── theme.ts                 # Colors, Spacing, Typography, BorderRadius
│   └── MockData.ts              # Mock data for all screens
├── hooks/
│   ├── use-color-scheme.ts      # React Native color scheme hook
│   └── use-theme-color.ts       # Theme-aware color lookup
└── src/api/
    └── ai.ts                    # Client for the FastAPI AI backend
```

---

## 🐍 AI Backend — `closetmate-ai/`

### Features
- **Background removal** from clothing photos using `rembg`
- **Editorial photo styling** — places the garment on a clean gradient background with drop shadow and lighting corrections
- **Clothing analysis** using **GPT-4o mini** (Vision) — returns category, color, and pattern
- **Lighting analysis** — detects brightness, contrast, and warmth to auto-correct images

### Tech Stack
| Tech | Purpose |
|---|---|
| FastAPI | REST API framework |
| Pillow | Image processing |
| rembg | AI background removal |
| OpenAI (GPT-4o mini) | Clothing attribute analysis via vision |
| NumPy | Pixel-level image analysis |

### API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/style-image` | Remove bg + editorial styling + lighting correction → returns JPEG |
| `POST` | `/analyze-clothing` | GPT-4o mini vision → returns `{ category, primary_color, pattern }` |
| `POST` | `/analyze-image` | Returns `{ brightness, contrast, warmth }` for a given image |
| `POST` | `/remove-background` | Standalone background removal → returns PNG |

### Getting Started

**Prerequisites:** Python 3.10+, an OpenAI API key

```bash
cd closetmate-ai

# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Set your OpenAI API key
set OPENAI_API_KEY=sk-...    # Windows
# export OPENAI_API_KEY=sk-... # macOS/Linux

# Run the server (main.py is the real entry point; app.py is a legacy single-file service)
uvicorn main:app --reload --port 8000

# Run the tests
pip install -r requirements-dev.txt
python -m pytest -q
```

Every endpoint except `/auth/*` and `/analyze-skin-tone` needs `Authorization: Bearer <token>` from
`POST /auth/login`. See `closetmate-ai/DEPLOY.md` for production settings.

The API will be available at `http://127.0.0.1:8000`.

> **Android Emulator Note:** If using an Android emulator, the app connects to `http://10.0.2.2:8000` by default. If that fails, set `ANDROID_HOST_OVERRIDE` in `closetmate/src/api/ai.ts` to your PC's local IP (e.g. `192.168.1.x`).

---

## 🔗 How They Connect

```
Mobile App  ──(POST /style-image)──►  FastAPI Backend
   │                                        │
   │   sends image URI                 removes bg
   │                                   styles photo
   │                                   returns JPEG
   │
   └── saves result to device filesystem
       (FileSystem.documentDirectory)
```

---

## 📄 License

MIT
