import random
import pytest
from unittest.mock import MagicMock

# Dummy implementations to simulate the behaviour of the real components.

class DummySignalGenerator:
    """Simulates generation and ranking of trading signals."""

    def __init__(self, connections, signals):
        self.connections = connections
        self._signals = signals

    def generate_signals(self):
        # In a real setup this would read from mempool streams per chain.
        return self._signals

    def rank_signals(self, signals=None):
        if signals is None:
            signals = self._signals
        # Higher priority first
        return sorted(signals, key=lambda x: x["priority"], reverse=True)


class DummyRiskManager:
    """Blocks risky transactions and can trigger a kill switch."""

    def __init__(self):
        self.kill_switch = False

    def is_risky(self, signal):
        return signal.get("risk", False)

    def check_kill_switch(self, signal):
        if signal.get("kill", False):
            self.kill_switch = True

    def should_execute(self, signal):
        self.check_kill_switch(signal)
        return not self.is_risky(signal) and not self.kill_switch


class DummySandwichBot:
    """Records executed transactions."""

    def __init__(self):
        self.executed = []

    def execute(self, tx):
        self.executed.append(tx)


class DummyOrchestrator:
    """Coordinates signal generation, risk checks, and execution."""

    def __init__(self, generator, bot, risk_manager):
        self.generator = generator
        self.bot = bot
        self.risk_manager = risk_manager

    def run(self):
        signals = self.generator.generate_signals()
        ranked = self.generator.rank_signals(signals)
        for signal in ranked:
            if self.risk_manager.should_execute(signal):
                self.bot.execute(signal["tx"])
            if self.risk_manager.kill_switch:
                break


# -------------------------- Fixtures --------------------------------------

@pytest.fixture
def mock_web3_connections():
    """Create mocked Web3 connections for multiple chains."""
    chains = ["ethereum", "polygon", "arbitrum", "optimism", "bsc"]
    return {chain: MagicMock(name=f"{chain}_web3") for chain in chains}


@pytest.fixture
def sample_signals():
    """Simulated mempool signals with different risks and priorities."""
    return [
        {"chain": "ethereum", "tx": "0xaaa", "priority": 100, "type": "liquidation"},
        {"chain": "polygon", "tx": "0xbbb", "priority": 90, "risk": True, "type": "sandwich"},
        {"chain": "bsc", "tx": "0xccc", "priority": 80, "type": "sandwich", "kill": True},
        {"chain": "optimism", "tx": "0xddd", "priority": 70, "type": "liquidation"},
    ]


@pytest.fixture

def orchestrator_components(mock_web3_connections, sample_signals):
    """Set up the orchestrator with dummy components."""
    generator = DummySignalGenerator(mock_web3_connections, sample_signals)
    bot = DummySandwichBot()
    risk = DummyRiskManager()
    orch = DummyOrchestrator(generator, bot, risk)
    return orch, generator, bot, risk


# -------------------------- Tests -----------------------------------------


def test_signal_generation_and_ranking(orchestrator_components):
    orch, generator, bot, risk = orchestrator_components
    signals = generator.generate_signals()
    ranked = generator.rank_signals(signals)

    # Verify that ranking sorts by priority descending
    priorities = [s["priority"] for s in ranked]
    assert priorities == sorted(priorities, reverse=True)


def test_orchestrator_dispatch_and_risk_block(orchestrator_components):
    orch, generator, bot, risk = orchestrator_components

    # Run orchestrator; risky tx should be blocked
    orch.run()

    # First signal is safe and executed, second is risky and skipped,
    # third triggers kill switch so last signal isn't executed.
    assert "0xaaa" in bot.executed
    assert "0xbbb" not in bot.executed
    assert risk.kill_switch
    assert "0xddd" not in bot.executed


def test_kill_switch_prevents_further_execution(orchestrator_components):
    orch, generator, bot, risk = orchestrator_components

    orch.run()
    # After kill switch, orchestrator should stop processing further signals
    assert risk.kill_switch
    # Ensure only transactions before kill switch executed
    assert bot.executed == ["0xaaa"]
