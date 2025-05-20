"""Chain configuration for multi-chain RPC connections."""

import os
from dataclasses import dataclass
from typing import Dict


@dataclass
class ChainConfig:
    """Simple container for chain connection information."""

    name: str
    rpc_url: str
    chain_id: int


CHAINS: Dict[str, ChainConfig] = {
    "ethereum": ChainConfig(
        name="ethereum",
        rpc_url=os.getenv("ETHEREUM_RPC", "https://mainnet.infura.io/v3/YOUR_API_KEY"),
        chain_id=1,
    ),
    "polygon": ChainConfig(
        name="polygon",
        rpc_url=os.getenv("POLYGON_RPC", "https://polygon-rpc.com"),
        chain_id=137,
    ),
    "arbitrum": ChainConfig(
        name="arbitrum",
        rpc_url=os.getenv("ARBITRUM_RPC", "https://arb1.arbitrum.io/rpc"),
        chain_id=42161,
    ),
    "optimism": ChainConfig(
        name="optimism",
        rpc_url=os.getenv("OPTIMISM_RPC", "https://mainnet.optimism.io"),
        chain_id=10,
    ),
    "bsc": ChainConfig(
        name="bsc",
        rpc_url=os.getenv("BSC_RPC", "https://bsc-dataseed.binance.org"),
        chain_id=56,
    ),
}
