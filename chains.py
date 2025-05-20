"""Web3 multi-chain connections with automatic failover.

This module exposes :class:`ChainConnection` for managing connections to
multiple blockchains. RPC URLs for Ethereum, Polygon, Arbitrum, Optimism
and BSC are read from environment variables ``<CHAIN>_RPC`` which may
contain one or more comma-separated HTTP or WebSocket endpoints.  Each
``ChainConnection`` maintains a background health check task that
periodically verifies connectivity and automatically fails over to the
next endpoint if the active one becomes unreachable.

Example
-------

>>> from chains import ETHEREUM
>>> ETHEREUM.web3.eth.block_number

Metrics hooks can be provided to integrate with Prometheus or similar
systems. The default hook simply logs metric values.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

from web3 import Web3

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------

MetricsHook = Callable[[str, float, Dict[str, str]], None]


def _default_metrics_hook(name: str, value: float, labels: Dict[str, str]) -> None:
    """Log metrics if no custom hook is provided."""

    logger.debug("METRIC %s value=%s labels=%s", name, value, labels)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _get_env_var(name: str) -> str:
    """Fetch an environment variable or raise a helpful error."""

    value = os.getenv(name)
    if not value:
        raise ValueError(f"Environment variable '{name}' is required")
    return value


def _parse_rpc_urls(value: str, name: str) -> List[str]:
    """Split and validate comma-separated RPC URLs."""

    urls = [u.strip() for u in value.split(",") if u.strip()]
    if not urls:
        raise ValueError(f"No RPC URLs provided for {name}")

    for url in urls:
        parts = urlparse(url)
        if parts.scheme not in {"http", "https", "ws", "wss"}:
            raise ValueError(
                f"Unsupported scheme '{parts.scheme}' in {name} RPC URL '{url}'"
            )
    return urls


def _create_web3_from_url(url: str, timeout: float) -> Web3:
    """Create a ``Web3`` instance for the given endpoint with timeout."""

    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"}:
        provider = Web3.HTTPProvider(url, request_kwargs={"timeout": timeout})
    elif parsed.scheme in {"ws", "wss"}:
        provider = Web3.WebsocketProvider(url, websocket_timeout=timeout)
    else:
        raise ValueError(f"Unsupported URL scheme '{parsed.scheme}' for {url}")
    return Web3(provider)


# ---------------------------------------------------------------------------
# ChainConnection class
# ---------------------------------------------------------------------------


class ChainConnection:
    """Manage a Web3 connection with automatic failover and health checks."""

    def __init__(
        self,
        name: str,
        urls: List[str],
        *,
        timeout: float = 10.0,
        health_check_interval: float = 30.0,
        metrics_hook: MetricsHook = _default_metrics_hook,
    ) -> None:
        self.name = name
        self.urls = urls
        self.timeout = timeout
        self.health_check_interval = health_check_interval
        self._metrics = metrics_hook

        self._lock = threading.RLock()
        self._active_idx = 0
        self.web3: Web3 = self._connect_initial()
        self._failover_count = 0
        self._uptime_start = time.time()

        # Start background health check thread
        self._stop_event = threading.Event()
        self._health_thread = threading.Thread(
            target=self._health_check_loop, name=f"{name}-health", daemon=True
        )
        self._health_thread.start()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect_initial(self) -> Web3:
        """Connect to the first responsive endpoint during initialization."""

        for idx, url in enumerate(self.urls):
            try:
                w3 = _create_web3_from_url(url, self.timeout)
                if w3.isConnected():
                    self._active_idx = idx
                    logger.info("Connected to %s via %s", self.name, url)
                    self._metrics(
                        "connection_established_total", 1, {"chain": self.name}
                    )
                    return w3
                logger.warning("%s unreachable at %s", self.name, url)
            except Exception as exc:  # pragma: no cover - log and continue
                logger.warning(
                    "%s connection attempt to %s failed: %s", self.name, url, exc
                )

        raise ConnectionError(f"All RPC endpoints failed for {self.name}")

    def _failover(self) -> None:
        """Attempt to connect to the next available endpoint."""

        start_idx = self._active_idx
        for offset in range(1, len(self.urls) + 1):
            idx = (start_idx + offset) % len(self.urls)
            url = self.urls[idx]
            try:
                w3 = _create_web3_from_url(url, self.timeout)
                if w3.isConnected():
                    with self._lock:
                        self.web3 = w3
                        self._active_idx = idx
                        self._uptime_start = time.time()
                        self._failover_count += 1
                    logger.warning("%s failover to %s", self.name, url)
                    self._metrics(
                        "failover_total", 1, {"chain": self.name}
                    )
                    return
                logger.warning("%s unreachable at %s", self.name, url)
            except Exception as exc:  # pragma: no cover - log and continue
                logger.warning(
                    "%s failover attempt to %s failed: %s", self.name, url, exc
                )
        raise ConnectionError(f"All failover attempts failed for {self.name}")

    def ensure_connection(self) -> None:
        """Check connection health and failover if necessary."""

        with self._lock:
            connected = self.web3.isConnected()
        if not connected:
            logger.warning("%s connection lost, initiating failover", self.name)
            self._failover()

    # ------------------------------------------------------------------
    # Background health checking
    # ------------------------------------------------------------------

    def _health_check_loop(self) -> None:
        while not self._stop_event.wait(self.health_check_interval):
            try:
                self.ensure_connection()
                uptime = time.time() - self._uptime_start
                self._metrics("uptime_seconds", uptime, {"chain": self.name})
            except Exception as exc:  # pragma: no cover - best-effort loop
                logger.error("Health check for %s failed: %s", self.name, exc)

    def close(self) -> None:
        """Stop the background health check thread."""

        self._stop_event.set()
        self._health_thread.join(timeout=1.0)

    # ------------------------------------------------------------------
    # Utility properties
    # ------------------------------------------------------------------

    @property
    def active_url(self) -> str:
        with self._lock:
            return self.urls[self._active_idx]

    @property
    def failover_count(self) -> int:
        with self._lock:
            return self._failover_count


# ---------------------------------------------------------------------------
# Global chain connections based on environment configuration
# ---------------------------------------------------------------------------


def _connection_from_env(name: str, env_var: str) -> ChainConnection:
    value = _get_env_var(env_var)
    urls = _parse_rpc_urls(value, name)
    return ChainConnection(name, urls)


ETHEREUM = _connection_from_env("Ethereum", "ETHEREUM_RPC")
POLYGON = _connection_from_env("Polygon", "POLYGON_RPC")
ARBITRUM = _connection_from_env("Arbitrum", "ARBITRUM_RPC")
OPTIMISM = _connection_from_env("Optimism", "OPTIMISM_RPC")
BSC = _connection_from_env("BSC", "BSC_RPC")

ALL_CHAINS: List[ChainConnection] = [ETHEREUM, POLYGON, ARBITRUM, OPTIMISM, BSC]

# What is exported when ``from chains import *`` is used
__all__ = [
    "ChainConnection",
    "ETHEREUM",
    "POLYGON",
    "ARBITRUM",
    "OPTIMISM",
    "BSC",
    "ALL_CHAINS",
]

