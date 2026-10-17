# SAP Purchase Order Confirmation Simulator

FastAPI + a static HTML page styled after SAP Fiori (Horizon theme): a list report with a filter bar and an object page per message. Real-time updates via Server-Sent Events (no reload). Data lives in memory and is lost on restart; this is a simulator.

## Structure
```
app/main.py           # API, webhook, SSE, simulator
app/static/index.html # UI (list report, object page, test controls)
test_webhook.py       # test script
```

## Install and run
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000 --timeout-graceful-shutdown 2
```
`--timeout-graceful-shutdown` matters: without it, `--reload` hangs while a browser tab holds the live (SSE) connection open, and code changes never load.
Open http://localhost:8000. Interactive API docs: http://localhost:8000/docs

## Login
Every page and API call requires signing in, except `POST /api/webhook` (protected by the optional `WEBHOOK_TOKEN`).
- Users are stored in `users.json` as PBKDF2 hashes (safe to commit).
- Manage them with:
  ```bash
  python manage_users.py add someone@artefact.com     # new user or password reset
  python manage_users.py remove someone@artefact.com
  python manage_users.py list
  ```
  Generated passwords are written to `credentials.local.txt` (git-ignored, never upload it). Commit the updated `users.json` to apply changes.
- `SECRET_KEY` env var signs session cookies (Render generates it via `render.yaml`). Without it, users are logged out on every restart. Sessions last 12 h.

## Webhook
`POST /api/webhook` with JSON:

| field | type | notes |
|---|---|---|
| `po_number` | string | |
| `vendor_email` | string | |
| `client_email` | string | |
| `order_details` | object or text | `items` (list), `currency`, `total`, `delivery_date` are shown in dedicated fields |
| `status` | string | `Created` (default), `Confirmed`, `Pending` (Spanish `Creada`/`Confirmada`/`Pendiente` also accepted) |

Returns `201 {"ok": true, "id": ...}`; invalid payload → `422`. Each call adds a new message to the inbox (history per PO).

### curl
```bash
curl -X POST http://localhost:8000/api/webhook -H "Content-Type: application/json" -d "{\"po_number\":\"4500012345\",\"vendor_email\":\"sales@supplier.com\",\"client_email\":\"purchasing@customer.com\",\"order_details\":{\"total\":1250.5,\"currency\":\"USD\"},\"status\":\"Confirmed\"}"
```

### Python
```bash
python test_webhook.py 4500012345 Confirmed
```

### Optional token
If the `WEBHOOK_TOKEN` env var is set, the webhook requires the header `X-Webhook-Token: <value>` (401 otherwise). Recommended when the app is public.

## Delete messages
- Select rows with the checkboxes → **Delete (n)**; the header checkbox selects all visible rows.
- **Delete All** empties the inbox. **Delete** on the object page removes that message.
- API: `DELETE /api/messages` (all), `POST /api/messages/delete` `{"ids": [...]}`, `DELETE /api/messages/{id}`.

## Deployment
Run it as **one instance with one worker**: messages live in memory, so several instances would each show different data. Data resets when the service restarts.

**Render (simplest, free tier):** push this folder to a GitHub repo → Render → *New → Blueprint* → pick the repo (uses `render.yaml`). URL: `https://<name>.onrender.com`. The free tier sleeps after ~15 min idle (first request takes ~1 min and resets data).

**Google Cloud Run (Dockerfile):**
```bash
gcloud run deploy sap-po-simulator --source . --region europe-west1 --allow-unauthenticated --max-instances 1 --timeout 3600 --set-env-vars WEBHOOK_TOKEN=change-me
```
`--max-instances 1` keeps a single shared inbox; `--timeout 3600` keeps the live (SSE) connection open longer (the browser reconnects automatically).

**Other Docker hosts** (Railway, Fly.io, Azure Container Apps): build with the `Dockerfile`; the app listens on `$PORT`.

### n8n / Make
HTTP Request node: method POST, URL `http://<host>:8000/api/webhook`, JSON body with the fields above. If the flow runs in the cloud, expose the port with a tunnel (e.g. `ngrok http 8000`).
