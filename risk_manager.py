"""Risk management utilities with FastAPI endpoints.

This module defines a :class:`RiskManager` for tracking live trading metrics
(PnL, slippage, gas cost, and latency). Thresholds are dynamically adjusted
according to market volatility, and the manager exposes Prometheus compatible
metrics via FastAPI endpoints. A kill switch is triggered when metrics breach
thresholds and optional webhook, email, and Slack alerts can be sent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
import ssl
import threading
import urllib.request
from dataclasses import dataclass, asdict
from email.message import EmailMessage
from typing import Callable, Dict, Optional

from fastapi import FastAPI, Response


@dataclass
class RiskMetrics:
    """Container for live risk metrics."""

    pnl: float = 0.0
    slippage: float = 0.0
    gas_cost: float = 0.0
    latency: float = 0.0


@dataclass
class RiskThresholds:
    """Base thresholds scaled by market volatility."""

    pnl: float
    slippage: float
    gas_cost: float
    latency: float
    volatility: float = 0.0

    def adjusted(self) -> Dict[str, float]:
        """Return thresholds adjusted for current volatility."""
        factor = 1 + self.volatility
        return {
            "pnl": self.pnl * factor,
            "slippage": self.slippage * factor,
            "gas_cost": self.gas_cost * factor,
            "latency": self.latency * factor,
        }


class RiskManager:
    """Monitor trading metrics and expose health endpoints."""

    def __init__(
        self,
        thresholds: RiskThresholds,
        *,
        webhook_url: Optional[str] = None,
        email_config: Optional[Dict[str, str]] = None,
        slack_webhook: Optional[str] = None,
        kill_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        self.metrics = RiskMetrics()
        self.base_thresholds = thresholds
        self.webhook_url = webhook_url
        self.email_config = email_config or {}
        self.slack_webhook = slack_webhook
        self.kill_callback = kill_callback

        self.killed = False
        self._lock = threading.Lock()
        self._logger = logging.getLogger(self.__class__.__name__)
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)
        self.app = FastAPI()
        self._setup_routes()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def update_metrics(self, *, pnl: float, slippage: float, gas_cost: float, latency: float) -> None:
        """Update metrics and check thresholds."""
        with self._lock:
            self.metrics.pnl = pnl
            self.metrics.slippage = slippage
            self.metrics.gas_cost = gas_cost
            self.metrics.latency = latency
        self._logger.debug("Metrics updated: %s", self.metrics)
        self._check_thresholds()

    def adjust_volatility(self, volatility: float) -> None:
        """Adjust thresholds based on market volatility."""
        self._logger.info("Adjusting volatility to %s", volatility)
        self.base_thresholds.volatility = volatility

    async def kill_switch(self) -> None:
        """Trigger kill switch and send alerts."""
        if self.killed:
            return
        self.killed = True
        self._logger.error("Kill switch activated")

        if self.webhook_url:
            await self._post_webhook({"event": "kill_switch"})

        if self.email_config:
            try:
                self._send_email_alert("Kill switch activated")
            except Exception as exc:  # pragma: no cover - external email
                self._logger.error("Email alert failed: %s", exc)

        if self.slack_webhook:
            await self._post_slack_alert("Kill switch activated")

        if self.kill_callback:
            try:
                self.kill_callback()
            except Exception as exc:  # pragma: no cover - external kill logic
                self._logger.error("Kill callback failed: %s", exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _check_thresholds(self) -> None:
        if self.killed:
            return
        with self._lock:
            metrics = asdict(self.metrics)
            thresholds = self.base_thresholds.adjusted()
        breached = [
            f"{m} {v} (limit {thresholds[m]})"
            for m, v in metrics.items()
            if abs(v) >= thresholds[m]
        ]
        if breached:
            for msg in breached:
                self._logger.warning("Threshold breached: %s", msg)
            asyncio.create_task(self.kill_switch())

    async def _post_webhook(self, payload: dict) -> None:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            self.webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, urllib.request.urlopen, req)

    def _send_email_alert(self, message: str) -> None:
        config = self.email_config
        msg = EmailMessage()
        msg["Subject"] = config.get("subject", "Risk Alert")
        msg["From"] = config.get("from")
        msg["To"] = config.get("to")
        msg.set_content(message)

        host = config.get("host")
        port = int(config.get("port", 0))
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=context) as server:
            user = config.get("user")
            password = config.get("password")
            if user and password:
                server.login(user, password)
            server.send_message(msg)

    async def _post_slack_alert(self, message: str) -> None:
        data = json.dumps({"text": message}).encode()
        req = urllib.request.Request(
            self.slack_webhook,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, urllib.request.urlopen, req)

    def _setup_routes(self) -> None:
        @self.app.get("/status")
        async def status() -> dict:
            return {"killed": self.killed}

        @self.app.get("/metrics")
        async def metrics() -> Response:
            text = self._prometheus_metrics()
            return Response(content=text, media_type="text/plain")

    def _prometheus_metrics(self) -> str:
        with self._lock:
            metrics = asdict(self.metrics)
        lines = [
            "# TYPE pnl gauge",
            f"pnl {metrics['pnl']}",
            "# TYPE slippage gauge",
            f"slippage {metrics['slippage']}",
            "# TYPE gas_cost gauge",
            f"gas_cost {metrics['gas_cost']}",
            "# TYPE latency gauge",
            f"latency {metrics['latency']}",
        ]
        return "\n".join(lines) + "\n"


__all__ = ["RiskManager", "RiskMetrics", "RiskThresholds"]
