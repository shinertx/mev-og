# mev-og

This repository contains a risk management module for monitoring trading metrics
such as PnL, slippage, gas costs and latency. The module exposes an HTTP API
implemented with FastAPI and outputs Prometheus compatible metrics.

The `risk_manager.py` module provides:

- Dynamic thresholding based on market volatility
- Webhook integration to signal an orchestrator when the kill switch activates
- Optional email and Slack alerts
- Asynchronous `/metrics` and `/status` endpoints for integration with
  monitoring systems

Unit tests cover basic kill-switch behaviour.
