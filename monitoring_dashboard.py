"""FastAPI monitoring dashboard with AI rationales and alerts.

This module exposes API endpoints and websocket streams for visualizing
live PnL, trade latency, gas usage, and risk metrics. It displays recent
trades with AI‑generated rationales and sends alerts via email or Slack.
Authentication uses simple JWT tokens with role based access control.
"""

import asyncio
import base64
import datetime
import hashlib
import hmac
import json
import os
import random
import smtplib
from email.message import EmailMessage
from typing import Dict, List, Optional

from fastapi import (Depends, FastAPI, HTTPException, WebSocket,
                     WebSocketDisconnect)
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover - fallback for environments without requests
    requests = None  # type: ignore

try:
    import openai  # type: ignore
except Exception:  # pragma: no cover - fallback when openai isn't installed
    openai = None  # type: ignore

app = FastAPI(
    title="Monitoring Dashboard",
    description="Dashboard visualising trading metrics with alerting and AI generated rationales",
)

templates = Jinja2Templates(directory="templates")

# --- Authentication using HMAC signed tokens ---------------------------------
SECRET_KEY = "change_this_secret"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# In-memory user database storing SHA256 hashed passwords
users_db: Dict[str, Dict[str, object]] = {
    "admin": {
        "hashed_password": hashlib.sha256("adminpass".encode()).hexdigest(),
        "roles": ["admin"],
    },
    "viewer": {
        "hashed_password": hashlib.sha256("viewpass".encode()).hexdigest(),
        "roles": ["viewer"],
    },
}

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


class User(BaseModel):
    username: str
    roles: List[str]


def _sign(data: bytes) -> bytes:
    return hmac.new(SECRET_KEY.encode(), data, hashlib.sha256).digest()


def create_access_token(data: dict, expires_delta: Optional[datetime.timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.datetime.utcnow() + (
        expires_delta if expires_delta else datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire.timestamp()})
    payload = json.dumps(to_encode).encode()
    token = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = base64.urlsafe_b64encode(_sign(payload)).decode().rstrip("=")
    return f"{token}.{signature}"


def decode_access_token(token: str) -> dict:
    try:
        payload_b64, sig_b64 = token.split(".")
        payload = base64.urlsafe_b64decode(payload_b64 + "==")
        signature = base64.urlsafe_b64decode(sig_b64 + "==")
        if not hmac.compare_digest(signature, _sign(payload)):
            raise ValueError("Invalid signature")
        data = json.loads(payload.decode())
        if data.get("exp", 0) < datetime.datetime.utcnow().timestamp():
            raise ValueError("Token expired")
        return data
    except Exception as exc:  # pragma: no cover - generic failure
        raise HTTPException(status_code=401, detail="Invalid authentication credentials") from exc


def authenticate_user(username: str, password: str) -> Optional[User]:
    user = users_db.get(username)
    if not user:
        return None
    hashed = hashlib.sha256(password.encode()).hexdigest()
    if hashed != user["hashed_password"]:
        return None
    return User(username=username, roles=list(user["roles"]))


def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    data = decode_access_token(token)
    username = data.get("sub")
    user = users_db.get(username)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    return User(username=username, roles=list(user["roles"]))


def require_role(role: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if role not in user.roles:
            raise HTTPException(status_code=403, detail="Insufficient privileges")
        return user

    return checker


# --- Data models --------------------------------------------------------------
class Metrics(BaseModel):
    timestamp: datetime.datetime
    pnl: float
    trade_latency_ms: float
    gas_usage_gwei: float
    risk_score: float


class Trade(BaseModel):
    trade_id: int
    timestamp: datetime.datetime
    asset: str
    quantity: float
    price: float
    rationale: str
    risk_score: float


# --- In-memory state ----------------------------------------------------------
latest_metrics: Metrics = Metrics(
    timestamp=datetime.datetime.utcnow(),
    pnl=0.0,
    trade_latency_ms=0.0,
    gas_usage_gwei=0.0,
    risk_score=0.0,
)

executed_trades: List[Trade] = []


# --- Alert manager ------------------------------------------------------------
class AlertManager:
    """Handles sending alerts via email or Slack."""

    def __init__(self, email_recipients: List[str], slack_webhook: str):
        self.email_recipients = email_recipients
        self.slack_webhook = slack_webhook

    def send_email_alert(self, subject: str, message: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["To"] = ",".join(self.email_recipients)
        msg.set_content(message)
        try:
            with smtplib.SMTP("localhost") as s:
                s.send_message(msg)
        except Exception:  # pragma: no cover - network failures
            print(f"[EMAIL ALERT] {subject}: {message}")

    def send_slack_alert(self, message: str) -> None:
        if requests is None:
            print(f"[SLACK ALERT] {message}")
            return
        try:
            requests.post(self.slack_webhook, json={"text": message}, timeout=5)
        except Exception:  # pragma: no cover - network failures
            print(f"[SLACK ALERT] {message}")


alert_manager = AlertManager(
    email_recipients=["ops@example.com"],
    slack_webhook=os.environ.get("SLACK_WEBHOOK", "https://hooks.slack.com/..."),
)

# --- Utility functions --------------------------------------------------------

def generate_ai_rationale(trade: Trade) -> str:
    """Generate a rationale via OpenAI if available."""
    if openai is None:
        return f"Executed {trade.asset} trade of {trade.quantity} units at {trade.price}."
    try:
        completion = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Provide a short trading rationale."},
                {
                    "role": "user",
                    "content": f"Asset: {trade.asset}, Qty: {trade.quantity}, Price: {trade.price}",
                },
            ],
        )
        return completion.choices[0].message["content"].strip()
    except Exception:  # pragma: no cover - network failures
        return f"Executed {trade.asset} trade of {trade.quantity} units at {trade.price}."


def update_metrics() -> None:
    global latest_metrics
    latest_metrics = Metrics(
        timestamp=datetime.datetime.utcnow(),
        pnl=latest_metrics.pnl + random.uniform(-10, 10),
        trade_latency_ms=random.uniform(50, 150),
        gas_usage_gwei=random.uniform(20, 200),
        risk_score=random.uniform(0, 1),
    )


def add_trade(asset: str, quantity: float, price: float) -> Trade:
    trade = Trade(
        trade_id=len(executed_trades) + 1,
        timestamp=datetime.datetime.utcnow(),
        asset=asset,
        quantity=quantity,
        price=price,
        rationale="",  # filled below
        risk_score=random.uniform(0, 1),
    )
    trade.rationale = generate_ai_rationale(trade)
    executed_trades.append(trade)
    return trade


# --- API endpoints ------------------------------------------------------------
@app.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    token = create_access_token({"sub": user.username})
    return {"access_token": token, "token_type": "bearer"}


@app.get("/metrics", response_model=Metrics)
def get_metrics(_: User = Depends(require_role("viewer"))):
    update_metrics()
    return latest_metrics


@app.get("/trades", response_model=List[Trade])
def get_trades(_: User = Depends(require_role("viewer"))):
    return executed_trades[-50:]


@app.post("/trades", response_model=Trade)
def execute_trade(
    asset: str,
    quantity: float,
    price: float,
    _: User = Depends(require_role("admin")),
):
    trade = add_trade(asset, quantity, price)
    if trade.risk_score > 0.8:
        alert_manager.send_email_alert("High Risk Trade", f"Trade {trade.trade_id} risk is high")
        alert_manager.send_slack_alert(f"High risk trade {trade.trade_id}")
    return trade


@app.post("/alert")
def manual_alert(message: str, _: User = Depends(require_role("admin"))):
    alert_manager.send_email_alert("Manual Alert", message)
    alert_manager.send_slack_alert(message)
    return {"status": "alert sent"}


@app.websocket("/ws/metrics")
async def websocket_metrics(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            update_metrics()
            await websocket.send_json(latest_metrics.dict())
            await asyncio.sleep(1)
    except WebSocketDisconnect:  # pragma: no cover - client disconnects
        pass


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return templates.TemplateResponse("dashboard.html", {"request": {}})
