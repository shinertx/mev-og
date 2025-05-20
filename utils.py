"""Utility module for Ethereum interactions.

This module provides helper functions for converting between Wei and Ether,
retrying blockchain transactions safely with exponential backoff, and
setting up application logging using ``loguru``.

It also offers asynchronous retry helpers, gas price prediction utilities and
sliding window aggregators for smoothing metrics.
"""

from typing import Callable, Type, Tuple, TypeVar
import asyncio
import functools
import random
import time
import sys
from statistics import mean
from collections import deque

from loguru import logger
from web3 import Web3

T = TypeVar("T")


def setup_logger(level: str = "INFO", json_log_file: str | None = None) -> None:
    """Configure loguru to output timestamped and leveled logs.

    Parameters
    ----------
    level : str
        Logging level for the logger. Defaults to ``"INFO"``.

    Examples
    --------
    >>> setup_logger()
    >>> logger.info("Logger configured!")

    Enable JSON logging:
    >>> setup_logger(json_log_file="app.json")
    """
    logger.remove()
    logger.add(
        sys.stdout,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        level=level,
    )
    if json_log_file:
        logger.add(json_log_file, serialize=True, level=level)


def wei_to_ether(value: int) -> float:
    """Convert Wei to Ether using Web3 utilities.

    Parameters
    ----------
    value : int
        The Wei amount to convert.

    Returns
    -------
    float
        The Ether value.

    Examples
    --------
    >>> wei_to_ether(1000000000000000000)
    1.0
    """
    return Web3.fromWei(value, "ether")


def ether_to_wei(value: float) -> int:
    """Convert Ether to Wei using Web3 utilities.

    Parameters
    ----------
    value : float
        The Ether amount to convert.

    Returns
    -------
    int
        The Wei value.

    Examples
    --------
    >>> ether_to_wei(1)
    1000000000000000000
    """
    return Web3.toWei(value, "ether")


def transaction_retry(
    exceptions: Tuple[Type[BaseException], ...],
    max_attempts: int = 3,
    initial_delay: float = 1.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator for retrying a function with exponential backoff.

    Parameters
    ----------
    exceptions : tuple of Exception classes
        Exceptions that trigger a retry when raised by the wrapped function.
    max_attempts : int, optional
        Maximum number of attempts. Defaults to ``3``.
    initial_delay : float, optional
        Time in seconds for the first backoff delay. Defaults to ``1.0``.

    Returns
    -------
    Callable
        A decorator that wraps the target function.

    Examples
    --------
    >>> @transaction_retry((ValueError,), max_attempts=2)
    ... def send_tx(tx):
    ...     return web3.eth.send_raw_transaction(tx)
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            attempt = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    attempt += 1
                    if attempt >= max_attempts:
                        logger.error(
                            "Maximum attempts reached (%s). Raising exception.",
                            max_attempts,
                        )
                        raise
                    logger.warning(
                        "Attempt %s failed with %s; retrying in %.2f seconds...",
                        attempt,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
                    delay *= 2
        return wrapper

    return decorator


def async_retry(
    exceptions: Tuple[Type[BaseException], ...],
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    jitter: float = 0.1,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Async decorator that retries a coroutine with exponential backoff and jitter.

    Parameters
    ----------
    exceptions : tuple of Exception classes
        Exceptions that trigger a retry when raised by the wrapped coroutine.
    max_attempts : int, optional
        Maximum number of attempts. Defaults to ``3``.
    initial_delay : float, optional
        Time in seconds for the first backoff delay. Defaults to ``1.0``.
    jitter : float, optional
        Random jitter added to the delay to avoid thundering herd issues.

    Returns
    -------
    Callable
        A decorator that wraps the target coroutine.

    Examples
    --------
    >>> @async_retry((TimeoutError,), max_attempts=5)
    ... async def fetch_data(web3):
    ...     return await web3.eth.block_number
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                delay = initial_delay
                attempt = 0
                while True:
                    try:
                        return await func(*args, **kwargs)
                    except exceptions as exc:
                        attempt += 1
                        if attempt >= max_attempts:
                            logger.error(
                                "Maximum attempts reached (%s). Raising exception.",
                                max_attempts,
                            )
                            raise
                        wait_time = delay + random.uniform(0, jitter)
                        logger.warning(
                            "Attempt %s failed with %s; retrying in %.2f seconds...",
                            attempt,
                            exc,
                            wait_time,
                        )
                        await asyncio.sleep(wait_time)
                        delay *= 2

            return wrapper
        else:
            # Fallback to synchronous retry if a regular function is provided
            return transaction_retry(
                exceptions, max_attempts=max_attempts, initial_delay=initial_delay
            )(func)

    return decorator


def predict_gas_price(web3: Web3, num_blocks: int = 5) -> int:
    """Estimate optimal gas price from recent blocks and mempool suggestion.

    Parameters
    ----------
    web3 : :class:`~web3.Web3`
        Instance connected to an Ethereum node.
    num_blocks : int, optional
        Number of recent blocks to analyze. Defaults to ``5``.

    Returns
    -------
    int
        Predicted gas price in Wei.

    Examples
    --------
    >>> w3 = Web3(Web3.EthereumTesterProvider())
    >>> predict_gas_price(w3)
    1000000000
    """

    latest = web3.eth.block_number
    base_fees = []
    for i in range(num_blocks):
        block = web3.eth.get_block(latest - i)
        fee = block.get("baseFeePerGas")
        if fee is not None:
            base_fees.append(fee)
    avg_base_fee = mean(base_fees) if base_fees else web3.eth.gas_price
    mempool_price = web3.eth.gas_price
    return max(int(avg_base_fee * 1.25), mempool_price)


class SlidingWindowAggregator:
    """Aggregate numeric metrics in a sliding window.

    Useful for smoothing series such as latency, profit and loss (PnL) or gas
    usage where short-term spikes would otherwise skew results.

    Parameters
    ----------
    size : int
        Number of samples to keep in the window.

    Examples
    --------
    >>> agg = SlidingWindowAggregator(size=3)
    >>> agg.add(1)
    >>> agg.add(2)
    >>> agg.mean()
    1.5
    """

    def __init__(self, size: int) -> None:
        self.size = size
        self.values: deque[float] = deque(maxlen=size)

    def add(self, value: float) -> None:
        """Add a new sample to the window."""

        self.values.append(value)

    def mean(self) -> float:
        """Return the mean of the window values."""

        if not self.values:
            return 0.0
        return sum(self.values) / len(self.values)

