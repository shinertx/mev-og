import asyncio
import logging

from chains import load_chains
from signal_generator import SignalGenerator
from risk_manager import RiskManager
from sandwich_bot import SandwichBot


class Orchestrator:
    """Main orchestration layer coordinating bots across multiple chains."""

    def __init__(self) -> None:
        # Load chain connections from chains.py
        self.chains = load_chains()
        self.signal_generators = {}
        self.risk_managers = {}
        self.sandwich_bots = {}
        self.tasks = []

        # Initialize core components for each chain
        for name, chain in self.chains.items():
            self.signal_generators[name] = SignalGenerator(chain)
            self.risk_managers[name] = RiskManager(chain)
            self.sandwich_bots[name] = SandwichBot(chain)

    async def start(self) -> None:
        """Start connections and background tasks."""
        logging.info("Starting orchestrator...")
        # Connect to each chain before launching worker tasks
        await asyncio.gather(*(chain.connect() for chain in self.chains.values()))

        for name in self.chains:
            bot = self.sandwich_bots[name]
            # Task to monitor mempool for this chain
            self.tasks.append(asyncio.create_task(bot.monitor_mempool()))
            # Task to fetch signals and execute strategies
            self.tasks.append(asyncio.create_task(self._signal_loop(name)))

        logging.info("Orchestrator started")

    async def stop(self) -> None:
        """Cancel background tasks and close connections."""
        logging.info("Stopping orchestrator...")

        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

        await asyncio.gather(*(chain.close() for chain in self.chains.values()))
        logging.info("Orchestrator stopped")

    async def _signal_loop(self, name: str) -> None:
        """Continuously fetch signals and execute approved strategies."""
        generator = self.signal_generators[name]
        risk = self.risk_managers[name]
        bot = self.sandwich_bots[name]

        while True:
            # Retrieve actionable signals for this chain
            signals = await generator.fetch_signals()
            for signal in signals:
                # Check risk before dispatching execution
                if risk.approve(signal):
                    await bot.execute(signal)
            await asyncio.sleep(0)  # yield control to other tasks


async def main() -> None:
    """Entry point for running the orchestrator."""
    logging.basicConfig(level=logging.INFO)
    orchestrator = Orchestrator()
    await orchestrator.start()
    try:
        # Run indefinitely until cancelled or interrupted
        while True:
            await asyncio.sleep(3600)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        await orchestrator.stop()


if __name__ == "__main__":
    asyncio.run(main())
