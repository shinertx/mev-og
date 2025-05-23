# coding: utf-8
"""Entry point for the MEV-OG trading system.

This module wires together the core components of the project and exposes a
``TradingSystem`` class used by ``python src/main.py``.  The implementation is
lightweight so tests can run without external dependencies while still
illustrating how orchestration, dependency injection and risk controls would
work in a real deployment.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from dataclasses import dataclass
from typing import Any, Optional

import config
from risk_manager import RiskManager, RiskThresholds


# ---------------------------------------------------------------------------
# Placeholder service classes used for orchestration.  Real implementations
# would live in separate modules.
# ---------------------------------------------------------------------------

class WalletService:
    """Very small wallet wrapper tracking the last used nonce."""

    def __init__(self) -> None:
        self.nonce = 0
        self.logger = logging.getLogger(self.__class__.__name__)

    async def healthy(self) -> bool:
        return True

    async def next_nonce(self) -> int:
        self.nonce += 1
        return self.nonce


class StrategyRegistry:
    """Registry returning dummy trade instructions."""

    async def fetch(self) -> list[dict[str, Any]]:
        # In reality this would query a DB or message queue.
        return []


class TxTracker:
    """Records dispatched transactions and their outcome."""

    def __init__(self) -> None:
        self.failures = 0
        self.logger = logging.getLogger(self.__class__.__name__)

    async def record_success(self, tx_hash: str) -> None:
        self.failures = 0
        self.logger.info("tx_success", extra={"tx": tx_hash})

    async def record_failure(self, tx_hash: str, reason: str) -> None:
        self.failures += 1
        self.logger.warning(
            "tx_failed", extra={"tx": tx_hash, "reason": reason, "failures": self.failures}
        )


class SimEngine:
    """Simple forked-mainnet simulation engine placeholder."""

    async def execute(self, trade: dict[str, Any]) -> str:
        # Simulated tx hash
        await asyncio.sleep(0.01)
        return f"0xs{hash(str(trade)) & 0xffff:x}"


# ---------------------------------------------------------------------------
# Trading System
# ---------------------------------------------------------------------------

@dataclass
class TradingSystem:
    wallet: WalletService
    risk_manager: RiskManager
    strategies: StrategyRegistry
    tracker: TxTracker
    sim: Optional[SimEngine] = None
    mode: str = "test"  # dry-run | live | test | sim
    health_interval: float = 5.0

    def __post_init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.stop_event = asyncio.Event()
        signal.signal(signal.SIGINT, lambda *_: asyncio.get_event_loop().call_soon_threadsafe(self.stop_event.set))
        signal.signal(signal.SIGTERM, lambda *_: asyncio.get_event_loop().call_soon_threadsafe(self.stop_event.set))

    # ------------------------------ Public API -----------------------------
    async def run(self) -> None:
        self.logger.info("system_start", extra={"mode": self.mode})
        health_task = asyncio.create_task(self._health_loop())
        try:
            while not self.stop_event.is_set() and not self.risk_manager.killed:
                trades = await self.strategies.fetch()
                for trade in trades:
                    if self.risk_manager.killed:
                        break
                    await self._process_trade(trade)
                await asyncio.sleep(0)
        finally:
            health_task.cancel()
            await asyncio.gather(health_task, return_exceptions=True)
            self.logger.info("system_stopped")

    # ------------------------------ Internals ------------------------------
    async def _health_loop(self) -> None:
        while not self.stop_event.is_set() and not self.risk_manager.killed:
            healthy = await self.wallet.healthy()
            if not healthy:
                self.logger.error("wallet_unhealthy")
                await self.risk_manager.kill_switch()
                break
            if self.tracker.failures >= 3:
                self.logger.error("circuit_breaker")
                await self.risk_manager.kill_switch()
                break
            await asyncio.sleep(self.health_interval)

    async def _process_trade(self, trade: dict[str, Any]) -> None:
        nonce = await self.wallet.next_nonce()
        expected_nonce = self.tracker.failures + 1
        if nonce != expected_nonce:
            self.logger.warning("nonce_mismatch", extra={"nonce": nonce, "expected": expected_nonce})
            await self.risk_manager.kill_switch()
            return

        try:
            if self.mode == "sim" and self.sim:
                tx_hash = await self.sim.execute(trade)
            else:
                # Placeholder for real transaction submission
                tx_hash = f"0x{hash(str(trade)) & 0xffff:x}"
            await self.tracker.record_success(tx_hash)
        except Exception as exc:  # pragma: no cover - placeholder
            await self.tracker.record_failure("0x0", str(exc))
            if self.tracker.failures >= 3:
                await self.risk_manager.kill_switch()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser(description="Run MEV-OG trading system")
    parser.add_argument("--mode", choices=["dry-run", "live", "test", "sim"], default=os.getenv("MODE", "test"))
    args = parser.parse_args()

    # (Re)load config for the chosen mode
    config.reload_config(None)

    wallet = WalletService()
    risk = RiskManager(RiskThresholds(pnl=10, slippage=1, gas_cost=5, latency=1))
    strategies = StrategyRegistry()
    tracker = TxTracker()
    sim = SimEngine() if args.mode == "sim" else None

    system = TradingSystem(wallet, risk, strategies, tracker, sim, mode=args.mode)
    await system.run()
    print("You should see system_stopped in the logs")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
