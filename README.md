# HelloRobotPrototype

A minimalist prototype of a **voice dispatch agent**. A single Python process
serves both the frontend and the backend:

* the **frontend** (plain HTML/CSS/JS) shows an incoming *demo call* you can
  answer with your microphone;
* the **backend** (FastAPI + WebSocket) bridges your microphone audio to the
  **Google Gemini Live API**, which speaks back in real time.

During the call the agent asks whether you can still fit in one more pickup
(one extra package) during your shift. When you answer, the agent calls the
`record_pickup_response` tool, says goodbye, and calls the `end_call` tool to
hang up. The interface then displays the recorded answer as formatted JSON,
ready to be stored in a database.

## How it works

```
browser  ──mic PCM 16 kHz (base64 over WebSocket)──▶  FastAPI  ──▶ Gemini Live API
browser  ◀──agent PCM 24 kHz + transcripts + JSON──  FastAPI  ◀──  (audio + tool calls)
```

| Path | Description |
| --- | --- |
| `app/main.py` | FastAPI app: static files, `/healthz`, `/ws/call` WebSocket bridge |
| `app/config.py` | Live API model, system instruction and tool declarations |
| `app/static/` | Minimal UI (`index.html`, `style.css`, `app.js`, `pcm-recorder.js`) |

Tools declared to the Live API (see
[Live API tools](https://ai.google.dev/gemini-api/docs/live-api/tools)):

* `record_pickup_response(accepted, reason, available_time_window, additional_notes, verbatim_answer)`
  — the server turns the arguments into the JSON record shown in the UI.
* `end_call(farewell)` — the server closes the call once the goodbye is played.

## Google Cloud / Gemini setup

1. Create (or reuse) a Google Cloud project.
2. Enable the **Generative Language API** (`generativelanguage.googleapis.com`)
   — this is the service that backs the Gemini Developer API and the Live API.
   The quickest way is to create the key in
   [Google AI Studio](https://aistudio.google.com/apikey), which enables the API
   in the selected project for you.
3. Copy the API key and set it as the `GOOGLE_API_KEY` environment variable.

> Only the Generative Language API is required. If you would rather run through
> Vertex AI instead of the Developer API, you must enable the **Vertex AI API**
> (`aiplatform.googleapis.com`) and use service-account credentials — this
> prototype uses the API key flow.

### Environment variables

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `GOOGLE_API_KEY` | ✅ | – | Gemini API key (`GEMINI_API_KEY` is also accepted) |
| `GEMINI_LIVE_MODEL` | ❌ | `gemini-2.0-flash-live-001` | Live API model |
| `GEMINI_LIVE_VOICE` | ❌ | `Puck` | Prebuilt voice name |
| `PORT` | ❌ | `8000` | Port the server listens on (Render sets this) |

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export GOOGLE_API_KEY="your-key"
uvicorn app.main:app --reload --port 8000
```

Open <http://localhost:8000>, click **Answer demo call** and allow microphone
access. Browsers only grant microphone access on `localhost` or over HTTPS.

Run the tests with:

```bash
pip install pytest httpx
python -m pytest
```

## Deploy on Render (web service)

The repository contains a `render.yaml` blueprint, so you can either use
**New → Blueprint** and point it at this repo, or create the service manually
with the settings below.

| Setting | Value |
| --- | --- |
| Type | **Web Service** |
| Language / Runtime | **Python 3** |
| Branch | `main` |
| Root directory | *(empty)* |
| Build command | `pip install -r requirements.txt` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Health check path | `/healthz` |
| Instance type | Free is enough for the demo |

Environment variables to add in **Settings → Environment**:

* `GOOGLE_API_KEY` = your Gemini API key (mark it as secret; never commit it)
* `PYTHON_VERSION` = `3.12.3` (optional, pins the runtime)
* `GEMINI_LIVE_MODEL` / `GEMINI_LIVE_VOICE` (optional overrides)

Notes for Render:

* Render terminates TLS for you, so the page is served over HTTPS and the
  browser can use `wss://` for the WebSocket — the frontend picks the scheme
  automatically.
* WebSockets work on Render without extra configuration, but free instances
  spin down when idle: the first call after a pause takes a few seconds.
* Keep a single worker (the default `uvicorn` command above); each call holds
  an in-memory Live API session.
