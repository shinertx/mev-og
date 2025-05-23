# mev-og

This project demonstrates a stripped down multi-chain MEV trading framework. It
contains placeholder implementations of sandwich bots, risk management and
monitoring utilities used in the integration tests.

## AGENTS

### src/main.py

`src/main.py` orchestrates the trading system. It loads configuration, creates
instances of `WalletService`, `RiskManager`, `StrategyRegistry`, `TxTracker` and
an optional `SimEngine` depending on the command line mode. The event loop
executes trades from the registry, performs health checks and activates the risk
manager kill switch when failures exceed thresholds. When running
`python src/main.py --mode test` you should see `system_stopped` in the logs
when the orchestrator exits.

Always run `pytest -q` before committing changes to ensure the risk management
behaviour is preserved.
