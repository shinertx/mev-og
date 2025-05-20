"""Placeholder sandwich bot implementation."""

import asyncio
import logging


class SandwichBot:
    """Executes sandwich strategies on a given chain."""

    def __init__(self, chain) -> None:
        self.chain = chain

    async def monitor_mempool(self) -> None:
        """Continuously monitor the chain's mempool."""
        logging.info("Monitoring mempool on %s", self.chain.config.name)
        while True:
            await asyncio.sleep(1)

    async def execute(self, signal) -> None:
        """Execute a sandwich strategy derived from ``signal``."""
        logging.info(
            "Executing sandwich strategy on %s for signal %s",
            self.chain.config.name,
            signal,
        )
        await asyncio.sleep(0.1)
