# Bank Nifty OI Analyzer

Frontend and backend are split so the UI can be deployed on Netlify and the API can be deployed separately on Render.

## Structure

```text
banknifty-oi-analyzer/
├── backend/
│   ├── app.py              # Flask API: login, health, AI analysis, Mongo history
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── index.html
│   ├── app.js              # CSV parsing, dashboard rendering, history UI
│   ├── style.css
│   ├── .env.example
│   └── config.js           # Default browser config
├── render.yaml             # Render backend blueprint
└── netlify.toml            # Netlify frontend config
```

## Backend Env

Set these in Render, or copy `backend/.env.example` to `backend/.env` locally. The backend also reads a root `.env` for local convenience, but `.env` files are ignored and must not be committed.

```env
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-6-luna
LOGIN_USERNAME=admin
LOGIN_PASSWORD=change_this_password
SECRET_KEY=change_this_to_a_long_random_string
MONGO_URI=mongodb+srv://user:password@cluster.mongodb.net/?retryWrites=true&w=majority
MONGO_DB_NAME=oi_analyzer
FRONTEND_ORIGIN=https://your-netlify-site.netlify.app
KITE_API_KEY=your_kite_api_key
KITE_API_SECRET=your_kite_api_secret
# Optional manual fallback. Leave blank when using /api/kite/login.
KITE_ACCESS_TOKEN=
KITE_SESSION_FILE=/var/data/kite_session.json
KITE_ENABLE_WEBSOCKET=false
LIVE_OPTIONS_STRIKES_EACH_SIDE=8
LIVE_OPTIONS_SNAPSHOT_SECONDS=180
```

The live options section keeps Kite credentials on the backend. It builds the NIFTY option chain from Kite's instrument master, uses REST quotes for snapshots, and can optionally enable one shared KiteTicker connection with `KITE_ENABLE_WEBSOCKET=true`. On Render, point `KITE_SESSION_FILE` at a persistent disk path if you want the Kite access token to survive process/container restarts.

Cron/keep-alive URL:

```text
https://your-render-backend.onrender.com/health
```

## Frontend Env

For local frontend, copy `frontend/.env.example` to `frontend/.env`:

```env
BACKEND_BASE_URL=https://banknifty-oi-analyzer-backend.onrender.com
```

For Netlify, publish the `frontend/` folder. The default frontend config points to the deployed Render backend.

## Run Locally

Backend:

```bash
cd backend
cp .env.example .env
python3 -m pip install -r requirements.txt
python3 app.py
```

Frontend:

```bash
cd frontend
python3 -m http.server 8080
```

Open:

```text
http://localhost:8080
```

The default local backend URL is `http://localhost:10000`.

## API

- `GET /health` - public health check for cron.
- `POST /api/login` - login with env username/password.
- `GET /api/kite/login` - redirect to Zerodha Kite login.
- `GET /api/kite/callback` - Kite redirect callback; exchanges `request_token` server-side.
- `GET /api/kite/status` - authenticated non-sensitive Kite auth/session status.
- `POST /api/kite/logout` - authenticated local Kite session logout.
- `GET /api/live-options/status` - authenticated Kite/live analyzer status.
- `GET /api/live-options/snapshot` - authenticated live NIFTY options intelligence snapshot.
- `POST /api/analyze` - authenticated AI analysis; saves each result to MongoDB.
- `GET /api/analyses` - authenticated history list.
- `GET /api/analyses/:id` - authenticated saved analysis detail.

## Disclaimer

For educational purposes only. Not SEBI-registered investment advice. Always use stop losses.
