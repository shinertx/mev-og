"""Configuration module for MEV-OG.

This module loads environment variables using :mod:`python-dotenv` and
exposes configuration constants. Critical variables are validated on
import and an :class:`EnvironmentError` is raised if any are missing.

RPC endpoints can be provided as comma-separated lists for failover, and
the :func:`reload_config` function allows runtime reloading of values.
"""

import os
from dotenv import load_dotenv

# Load variables from a .env file located in the project root (if present)
load_dotenv()


def _parse_list(value: str | None) -> list[str]:
    """Parse a comma-separated list from *value*."""
    return [item.strip() for item in value.split(",") if item.strip()] if value else []


def _load_config(dotenv_path: str | None = None) -> None:
    """Load or reload configuration from environment variables."""
    load_dotenv(dotenv_path, override=True)

    global MODE
    global PRIVATE_KEY, PUBLIC_ADDRESS
    global ETH_RPC_URL, POLYGON_RPC_URL, ARBITRUM_RPC_URL, OPTIMISM_RPC_URL, BSC_RPC_URL
    global ETH_RPC_URLS, POLYGON_RPC_URLS, ARBITRUM_RPC_URLS, OPTIMISM_RPC_URLS, BSC_RPC_URLS
    global FLASHBOTS_SIGNING_KEY, FLASHBOTS_SIGNING_ADDRESS
    global TARGET_PROFIT, STARTING_CAPITAL
    global WETH_ADDRESS, USDC_ADDRESS
    global ALERT_EMAIL_RECIPIENTS, SLACK_WEBHOOK_URL

    MODE = os.getenv("MODE", "test")

    PRIVATE_KEY = os.getenv("PRIVATE_KEY")
    PUBLIC_ADDRESS = os.getenv("PUBLIC_ADDRESS")

    ETH_RPC_URL = os.getenv("ETH_RPC_URL")
    ETH_RPC_URLS = _parse_list(os.getenv("ETH_RPC_URLS")) or (
        [ETH_RPC_URL] if ETH_RPC_URL else []
    )

    POLYGON_RPC_URL = os.getenv("POLYGON_RPC_URL")
    POLYGON_RPC_URLS = _parse_list(os.getenv("POLYGON_RPC_URLS")) or (
        [POLYGON_RPC_URL] if POLYGON_RPC_URL else []
    )

    ARBITRUM_RPC_URL = os.getenv("ARBITRUM_RPC_URL")
    ARBITRUM_RPC_URLS = _parse_list(os.getenv("ARBITRUM_RPC_URLS")) or (
        [ARBITRUM_RPC_URL] if ARBITRUM_RPC_URL else []
    )

    OPTIMISM_RPC_URL = os.getenv("OPTIMISM_RPC_URL")
    OPTIMISM_RPC_URLS = _parse_list(os.getenv("OPTIMISM_RPC_URLS")) or (
        [OPTIMISM_RPC_URL] if OPTIMISM_RPC_URL else []
    )

    BSC_RPC_URL = os.getenv("BSC_RPC_URL")
    BSC_RPC_URLS = _parse_list(os.getenv("BSC_RPC_URLS")) or (
        [BSC_RPC_URL] if BSC_RPC_URL else []
    )

    FLASHBOTS_SIGNING_KEY = os.getenv("FLASHBOTS_SIGNING_KEY")
    FLASHBOTS_SIGNING_ADDRESS = os.getenv("FLASHBOTS_SIGNING_ADDRESS")

    TARGET_PROFIT = float(os.getenv("TARGET_PROFIT", "0"))
    STARTING_CAPITAL = float(os.getenv("STARTING_CAPITAL", "0"))

    WETH_ADDRESS = os.getenv(
        "WETH_ADDRESS",
        _DEFAULT_ADDRESSES["WETH"]["mainnet" if MODE == "mainnet" else "test"],
    )
    USDC_ADDRESS = os.getenv(
        "USDC_ADDRESS",
        _DEFAULT_ADDRESSES["USDC"]["mainnet" if MODE == "mainnet" else "test"],
    )

    ALERT_EMAIL_RECIPIENTS = _parse_list(os.getenv("ALERT_EMAIL_RECIPIENTS"))
    SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

    _validate_required()


def _validate_required() -> None:
    """Ensure all critical variables are present."""
    critical = {
        "PRIVATE_KEY": PRIVATE_KEY,
        "PUBLIC_ADDRESS": PUBLIC_ADDRESS,
        "ETH_RPC_URL": ETH_RPC_URL,
        "FLASHBOTS_SIGNING_KEY": FLASHBOTS_SIGNING_KEY,
        "FLASHBOTS_SIGNING_ADDRESS": FLASHBOTS_SIGNING_ADDRESS,
    }
    missing = [name for name, value in critical.items() if not value]
    if missing:
        raise EnvironmentError(
            "Missing required environment variables: " + ", ".join(missing)
        )


def reload_config(dotenv_path: str | None = None) -> None:
    """Public API to reload configuration at runtime."""
    _load_config(dotenv_path)

# -----------------------------------------------------------------------------
# Placeholders for configuration values
# -----------------------------------------------------------------------------

# Network mode: 'mainnet' or 'test'
MODE: str

# Wallet configuration
PRIVATE_KEY: str | None
PUBLIC_ADDRESS: str | None

# RPC endpoints
ETH_RPC_URL: str | None
POLYGON_RPC_URL: str | None
ARBITRUM_RPC_URL: str | None
OPTIMISM_RPC_URL: str | None
BSC_RPC_URL: str | None

# Failover RPC URL lists
ETH_RPC_URLS: list[str]
POLYGON_RPC_URLS: list[str]
ARBITRUM_RPC_URLS: list[str]
OPTIMISM_RPC_URLS: list[str]
BSC_RPC_URLS: list[str]

# Flashbots configuration
FLASHBOTS_SIGNING_KEY: str | None
FLASHBOTS_SIGNING_ADDRESS: str | None

# Strategy parameters
TARGET_PROFIT: float
STARTING_CAPITAL: float

# Token addresses (set in _load_config)
WETH_ADDRESS: str
USDC_ADDRESS: str

# Alerting configuration
ALERT_EMAIL_RECIPIENTS: list[str]
SLACK_WEBHOOK_URL: str | None

# -----------------------------------------------------------------------------
# Token addresses
# -----------------------------------------------------------------------------

_DEFAULT_ADDRESSES = {
    "WETH": {
        "mainnet": "0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2",
        "test": "0xB4FBF271143F4FBf7B91A5ded31805e42b2208d6",
    },
    "USDC": {
        "mainnet": "0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        "test": "0x07865c6e87b9f70255377e024ace6630c1eaa37f",
    },
}

# Initialise configuration from environment on import
_load_config()

__all__ = [
    "MODE",
    "PRIVATE_KEY",
    "PUBLIC_ADDRESS",
    "ETH_RPC_URL",
    "POLYGON_RPC_URL",
    "ARBITRUM_RPC_URL",
    "OPTIMISM_RPC_URL",
    "BSC_RPC_URL",
    "ETH_RPC_URLS",
    "POLYGON_RPC_URLS",
    "ARBITRUM_RPC_URLS",
    "OPTIMISM_RPC_URLS",
    "BSC_RPC_URLS",
    "FLASHBOTS_SIGNING_KEY",
    "FLASHBOTS_SIGNING_ADDRESS",
    "TARGET_PROFIT",
    "STARTING_CAPITAL",
    "WETH_ADDRESS",
    "USDC_ADDRESS",
    "ALERT_EMAIL_RECIPIENTS",
    "SLACK_WEBHOOK_URL",
    "reload_config",
]
