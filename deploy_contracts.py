import argparse
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from web3 import Web3
from solcx import compile_standard, install_solc


logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


def compile_contract(contract_path: Path, solc_version: str = "0.8.17"):
    """Compile a Solidity contract and return its ABI and bytecode."""
    if not contract_path.exists():
        raise FileNotFoundError(f"Contract not found: {contract_path}")

    logging.info("Installing solc %s if necessary", solc_version)
    install_solc(solc_version)

    source = contract_path.read_text()
    compiled = compile_standard(
        {
            "language": "Solidity",
            "sources": {contract_path.name: {"content": source}},
            "settings": {
                "outputSelection": {
                    "*": {
                        "*": ["abi", "evm.bytecode"]
                    }
                }
            },
        },
        solc_version=solc_version,
    )

    contract_name = next(iter(compiled["contracts"][contract_path.name]))
    abi = compiled["contracts"][contract_path.name][contract_name]["abi"]
    bytecode = compiled["contracts"][contract_path.name][contract_name]["evm"]["bytecode"]["object"]
    return abi, bytecode


def deploy(network: str, pool: str, min_profit: int, contract_path: Path):
    """Deploy the LiquidationFlashLoan contract."""
    env_rpc_var = f"{network.upper()}_RPC_URL"
    load_dotenv()
    rpc_url = os.environ.get(env_rpc_var)
    private_key = os.environ.get("PRIVATE_KEY")

    if not rpc_url:
        raise EnvironmentError(f"Missing {env_rpc_var} in environment")
    if not private_key:
        raise EnvironmentError("Missing PRIVATE_KEY in environment")

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    account = w3.eth.account.from_key(private_key)
    logging.info("Using account %s", account.address)

    abi, bytecode = compile_contract(contract_path)
    contract = w3.eth.contract(abi=abi, bytecode=bytecode)

    nonce = w3.eth.get_transaction_count(account.address)
    txn = contract.constructor(pool, min_profit).build_transaction({
        "from": account.address,
        "nonce": nonce,
        "gasPrice": w3.eth.gas_price,
    })

    signed = account.sign_transaction(txn)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    logging.info("Deployment transaction sent: %s", tx_hash.hex())

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    logging.info("Contract deployed at: %s", receipt.contractAddress)

    return receipt.contractAddress


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy LiquidationFlashLoan contract")
    parser.add_argument("--network", choices=["goerli", "sepolia"], required=True,
                        help="Target testnet")
    parser.add_argument("--pool", required=True, help="Pool address for constructor")
    parser.add_argument("--min-profit", type=int, required=True, help="Minimum profit in wei")
    parser.add_argument("--contract-path", default="contracts/LiquidationFlashLoan.sol",
                        help="Path to Solidity contract")
    args = parser.parse_args()

    try:
        address = deploy(args.network, args.pool, args.min_profit, Path(args.contract_path))
        print(f"Deployed to: {address}")
    except Exception as exc:
        logging.error("Deployment failed: %s", exc)
        raise SystemExit(1)

