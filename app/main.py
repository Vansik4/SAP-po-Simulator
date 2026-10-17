"""SAP Purchase Order Confirmation Simulator.

FastAPI backend:
  POST   /api/webhook        -> receives PO confirmations (JSON)
  GET    /api/messages       -> inbox (list of messages)
  GET    /api/messages/{id}  -> message detail
  POST   /api/simulate       -> test controls (create sample PO / confirm / pending)
  DELETE /api/messages       -> clear inbox
  GET    /api/stream         -> Server-Sent Events for real-time updates
"""
import asyncio
import json
import os
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import auth

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
WEBHOOK_TOKEN = os.environ.get("WEBHOOK_TOKEN")  # optional shared secret for the webhook

Status = Literal["Created", "Confirmed", "Pending"]

# Spanish values are still accepted so existing flows keep working.
STATUS_ALIASES = {
    "created": "Created", "creada": "Created",
    "confirmed": "Confirmed", "confirmada": "Confirmed",
    "pending": "Pending", "pendiente": "Pending",
}

app = FastAPI(title="SAP PO Confirmation Simulator")

# Reachable without a session. The webhook has its own optional token (WEBHOOK_TOKEN).
PUBLIC_PATHS = {"/login", "/api/login", "/api/webhook", "/favicon.ico"}


@app.middleware("http")
async def require_login(request: Request, call_next):
    """Every page and API call needs a valid session cookie, except PUBLIC_PATHS."""
    path = request.url.path
    if path in PUBLIC_PATHS:
        return await call_next(request)
    user = auth.read_session(request.cookies.get(auth.COOKIE_NAME))
    if not user:
        if path.startswith("/api/") or path in ("/docs", "/redoc", "/openapi.json"):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    request.state.user = user
    return await call_next(request)


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------
class WebhookPayload(BaseModel):
    po_number: str = Field(..., min_length=1)
    vendor_email: str = Field(..., min_length=3)
    client_email: str = Field(..., min_length=3)
    order_details: Any = Field(..., description="JSON object or free text")
    status: Status = "Created"

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, v):
        if isinstance(v, str):
            return STATUS_ALIASES.get(v.strip().lower(), v)
        return v


class SimulateRequest(BaseModel):
    action: Literal["create_sample", "vendor_confirms", "vendor_pending"]
    po_number: Optional[str] = None  # required for confirms/pending


class DeleteRequest(BaseModel):
    ids: list[str] = Field(..., min_length=1)


class LoginRequest(BaseModel):
    email: str
    password: str


# --------------------------------------------------------------------------
# In-memory store + broadcast to SSE subscribers
# --------------------------------------------------------------------------
class Store:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.subscribers: set[asyncio.Queue] = set()

    def add(self, p: WebhookPayload, source: str) -> dict:
        msg = {
            "id": uuid.uuid4().hex[:12],
            "po_number": p.po_number,
            "vendor": p.vendor_email,
            "client": p.client_email,
            "status": p.status,
            "source": source,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "order_details": p.order_details,
            "subject": f"Purchase Order {p.po_number} - {p.status}",
            "body": render_body(p),
        }
        self.messages.insert(0, msg)  # newest first
        self.publish({"type": "new_message", "message": summary(msg)})
        return msg

    def publish(self, event: dict) -> None:
        for q in list(self.subscribers):
            q.put_nowait(event)

    def clear(self) -> None:
        self.messages.clear()
        self.publish({"type": "cleared"})

    def delete(self, ids: set[str]) -> list[str]:
        removed = [m["id"] for m in self.messages if m["id"] in ids]
        self.messages = [m for m in self.messages if m["id"] not in ids]
        if removed:
            self.publish({"type": "deleted", "ids": removed})
        return removed


store = Store()


def summary(m: dict) -> dict:
    """Lightweight version for the table (no body)."""
    return {k: m[k] for k in ("id", "po_number", "vendor", "client", "status", "source", "created_at", "subject")}


STATUS_SENTENCE = {
    "Created": "has been created and transmitted to the supplier",
    "Confirmed": "has been CONFIRMED by the supplier",
    "Pending": "is PENDING supplier confirmation",
}


def render_body(p: WebhookPayload) -> str:
    """Builds the confirmation email text."""
    d = p.order_details
    if isinstance(d, (dict, list)):
        details = json.dumps(d, indent=2, ensure_ascii=False)
    else:
        details = str(d)
    return (
        f"Dear Customer,\n\n"
        f"Please be advised that Purchase Order {p.po_number} {STATUS_SENTENCE[p.status]}.\n\n"
        f"Order details:\n{details}\n\n"
        f"Supplier: {p.vendor_email}\n\n"
        f"Kind regards,\n"
        f"SAP Business Network (simulated)\n\n"
        f"This is an automatically generated message. Please do not reply."
    )


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@app.post("/api/webhook", status_code=201)
async def webhook(payload: WebhookPayload, x_webhook_token: Optional[str] = Header(None)):
    """Receives a JSON payload from n8n / Make / action flows / scripts.

    If the WEBHOOK_TOKEN env var is set, callers must send it in the X-Webhook-Token header.
    """
    if WEBHOOK_TOKEN and x_webhook_token != WEBHOOK_TOKEN:
        raise HTTPException(401, "Invalid or missing X-Webhook-Token header")
    msg = store.add(payload, source="Webhook")
    return {"ok": True, "id": msg["id"], "po_number": msg["po_number"], "status": msg["status"]}


@app.get("/api/messages")
async def list_messages():
    return [summary(m) for m in store.messages]


@app.get("/api/messages/{msg_id}")
async def get_message(msg_id: str):
    for m in store.messages:
        if m["id"] == msg_id:
            return m
    raise HTTPException(404, "Message not found")


@app.delete("/api/messages")
async def clear_messages():
    """Deletes every message in the inbox."""
    store.clear()
    return {"ok": True}


@app.post("/api/messages/delete")
async def delete_messages(req: DeleteRequest):
    """Deletes the selected messages."""
    removed = store.delete(set(req.ids))
    return {"ok": True, "deleted": len(removed)}


@app.delete("/api/messages/{msg_id}")
async def delete_message(msg_id: str):
    if not store.delete({msg_id}):
        raise HTTPException(404, "Message not found")
    return {"ok": True}


SAMPLE_MATERIALS = [
    ("MAT-1001", "Hex Bolt M8x40 Zinc", "EA", 0.42),
    ("MAT-2040", "Flat Washer 8mm", "EA", 0.08),
    ("MAT-3105", "Hydraulic Hose 1/2in", "M", 6.75),
    ("MAT-4410", "Ball Bearing 6204-2RS", "EA", 3.90),
    ("MAT-5022", "Safety Gloves L", "PR", 2.15),
]


def sample_order() -> dict:
    items = []
    for i, (mat, desc, unit, price) in enumerate(random.sample(SAMPLE_MATERIALS, k=random.randint(2, 4)), 1):
        qty = random.randint(10, 500)
        items.append({
            "item": i * 10,
            "material": mat,
            "description": desc,
            "quantity": qty,
            "unit": unit,
            "net_price": price,
            "net_value": round(qty * price, 2),
        })
    return {
        "items": items,
        "currency": "USD",
        "total": round(sum(i["net_value"] for i in items), 2),
        "delivery_date": (datetime.now() + timedelta(days=random.randint(7, 30))).date().isoformat(),
        "plant": "1010",
        "purchasing_group": "001",
        "payment_terms": "NT30",
    }


@app.post("/api/simulate", status_code=201)
async def simulate(req: SimulateRequest):
    """Test controls: triggers manual events."""
    if req.action == "create_sample":
        po = req.po_number or f"45{random.randint(10000000, 99999999)}"
        payload = WebhookPayload(
            po_number=po,
            vendor_email="sales@supplier-demo.com",
            client_email="purchasing@customer-demo.com",
            order_details=sample_order(),
            status="Created",
        )
        return summary(store.add(payload, source="Simulator"))

    # vendor_confirms / vendor_pending: based on the latest version of that PO
    if not req.po_number:
        raise HTTPException(422, "po_number is required for this action")
    last = next((m for m in store.messages if m["po_number"] == req.po_number), None)
    if not last:
        raise HTTPException(404, f"Purchase Order {req.po_number} does not exist")
    new_status: Status = "Confirmed" if req.action == "vendor_confirms" else "Pending"
    payload = WebhookPayload(
        po_number=last["po_number"],
        vendor_email=last["vendor"],
        client_email=last["client"],
        order_details=last["order_details"],
        status=new_status,
    )
    return summary(store.add(payload, source="Simulator"))


@app.get("/api/stream")
async def stream():
    """SSE: pushes events to the browser without reloading."""
    queue: asyncio.Queue = asyncio.Queue()
    store.subscribers.add(queue)

    async def gen():
        try:
            yield ": connected\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            store.subscribers.discard(queue)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


# --------------------------------------------------------------------------
# Login / logout
# --------------------------------------------------------------------------
@app.get("/login")
async def login_page(request: Request):
    if auth.read_session(request.cookies.get(auth.COOKIE_NAME)):
        return RedirectResponse("/", status_code=303)
    return FileResponse(STATIC_DIR / "login.html")


@app.post("/api/login")
async def login(req: LoginRequest, request: Request, response: Response):
    email = auth.authenticate(req.email, req.password)
    if not email:
        await asyncio.sleep(1)  # slows down password guessing
        raise HTTPException(401, "Invalid email or password")
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(auth.COOKIE_NAME, auth.make_session(email), max_age=auth.SESSION_SECONDS,
                        httponly=True, samesite="lax", secure=secure)
    return {"ok": True, "email": email}


@app.post("/api/logout")
async def logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


@app.get("/api/me")
async def me(request: Request):
    return {"email": request.state.user}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
