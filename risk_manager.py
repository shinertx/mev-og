"""Placeholder risk management logic."""

import logging


class RiskManager:
    """Evaluates risk for potential trades."""

    def __init__(self, chain) -> None:
        self.chain = chain

    def approve(self, signal) -> bool:
        """Return True if the trade associated with ``signal`` is allowed."""
        logging.debug("Risk check for %s: %s", self.chain.config.name, signal)
        return True
