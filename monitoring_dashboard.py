"""Monitoring Dashboard using FastAPI

This module provides a simple example of how a monitoring dashboard for
algorithmic trading might be implemented. It exposes REST endpoints and a
lightweight web UI to visualize key metrics such as PnL, trade latency, gas
usage, and risk metrics. It demonstrates user authentication, role-based access
control, and a modular design with separate routers for metrics, alerts, and
user management.

The implementation stores example data in memory and uses placeholders for
functionality such as AI-generated trade explanations and alert delivery to
email/Slack. In a real system, these would hook into external services or
infrastructure.
"""

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Dict, Optional

app = FastAPI(title="Monitoring Dashboard")

# In-memory example data
users_db: Dict[str, Dict[str, str]] = {
    "alice": {"username": "alice", "password": "secret", "role": "admin"},
    "bob": {"username": "bob", "password": "password", "role": "viewer"},
}

trades = [
    {
        "id": 1,
        "symbol": "ETH/USD",
        "quantity": 1.5,
        "price": 2000,
        "pnl": 150,
        "latency_ms": 120,
        "gas_used": 50000,
        "risk": 0.02,
    },
    {
        "id": 2,
        "symbol": "BTC/USD",
        "quantity": 0.1,
        "price": 30000,
        "pnl": -50,
        "latency_ms": 200,
        "gas_used": 40000,
        "risk": 0.01,
    },
]

alerts: List[str] = []

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

# Simple user authentication and role based access control
async def get_current_user(token: str = Depends(oauth2_scheme)):
    user = users_db.get(token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid authentication credentials")
    return user

def require_role(role: str):
    async def role_dependency(user: Dict = Depends(get_current_user)):
        if user.get("role") != role:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Not enough privileges")
        return user
    return role_dependency

# Pydantic models for API responses
class Trade(BaseModel):
    id: int
    symbol: str
    quantity: float
    price: float
    pnl: float
    latency_ms: int
    gas_used: int
    risk: float
    explanation: Optional[str] = None

class Alert(BaseModel):
    message: str

# Routers for modularity
metrics_router = APIRouter(prefix="/metrics", tags=["metrics"])
alerts_router = APIRouter(prefix="/alerts", tags=["alerts"])
users_router = APIRouter(prefix="/users", tags=["users"])

@metrics_router.get("/trades", response_model=List[Trade])
async def get_trades(user: Dict = Depends(get_current_user)):
    """Return recent trades with dummy AI explanations."""
    result = []
    for t in trades:
        explanation = f"Executed trade {t['id']} in {t['symbol']} with PnL {t['pnl']}"
        result.append(Trade(**t, explanation=explanation))
    return result

@metrics_router.get("/pnl")
async def get_pnl(user: Dict = Depends(get_current_user)):
    """Aggregate PnL from example trades."""
    total_pnl = sum(t["pnl"] for t in trades)
    return {"total_pnl": total_pnl}

@alerts_router.post("/", response_model=Alert)
async def create_alert(alert: Alert, user: Dict = Depends(require_role("admin"))):
    """Create an alert and simulate sending it via email/Slack."""
    alerts.append(alert.message)
    # Placeholder for sending alerts via email or Slack
    print(f"ALERT: {alert.message}")
    return alert

@alerts_router.get("/", response_model=List[str])
async def list_alerts(user: Dict = Depends(require_role("admin"))):
    """List all recorded alerts."""
    return alerts

@users_router.post("/", dependencies=[Depends(require_role("admin"))])
async def create_user(username: str, password: str, role: str = "viewer"):
    """Create a new user."""
    if username in users_db:
        raise HTTPException(status_code=400, detail="User already exists")
    users_db[username] = {"username": username, "password": password, "role": role}
    return {"username": username, "role": role}

@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Authenticate a user and return a token (the username in this example)."""
    user = users_db.get(form_data.username)
    if not user or user["password"] != form_data.password:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    return {"access_token": user["username"], "token_type": "bearer"}

@app.get("/", response_class=HTMLResponse)
async def dashboard(user: Dict = Depends(get_current_user)):
    """Return a basic HTML dashboard displaying metrics."""
    total_pnl = sum(t["pnl"] for t in trades)
    return f"""
    <html>
        <head><title>Monitoring Dashboard</title></head>
        <body>
            <h1>Welcome, {user['username']}!</h1>
            <p>Total PnL: {total_pnl}</p>
            <p>Number of Trades: {len(trades)}</p>
            <p>Alerts: {len(alerts)}</p>
        </body>
    </html>
    """

# Include routers in the main app
app.include_router(metrics_router)
app.include_router(alerts_router)
app.include_router(users_router)

if __name__ == "__main__":
    import uvicorn
    # Run with: python monitoring_dashboard.py
    uvicorn.run(app, host="0.0.0.0", port=8000)
