diff --git a//dev/null b/deploy_contracts.py
index 0000000..b11658b 100644
--- a//dev/null
+++ b/deploy_contracts.py
@@ -0,0 +1,175 @@
+import argparse
+import json
+import logging
+import os
+from pathlib import Path
+
+from dotenv import load_dotenv
+from web3 import Web3
+from solcx import compile_standard, install_solc
+
+
+logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
+
+
+def compile_contract(contract_path: Path, solc_version: str = "0.8.17"):
+    """Compile a Solidity contract and return its ABI and bytecode."""
+    if not contract_path.exists():
+        raise FileNotFoundError(f"Contract not found: {contract_path}")
+
+    logging.info("Installing solc %s if necessary", solc_version)
+    install_solc(solc_version)
+
+    source = contract_path.read_text()
+    compiled = compile_standard(
+        {
+            "language": "Solidity",
+            "sources": {contract_path.name: {"content": source}},
+            "settings": {
+                "outputSelection": {
+                    "*": {
+                        "*": ["abi", "evm.bytecode"]
+                    }
+                }
+            },
+        },
+        solc_version=solc_version,
+    )
+
+    contract_name = next(iter(compiled["contracts"][contract_path.name]))
+    abi = compiled["contracts"][contract_path.name][contract_name]["abi"]
+    bytecode = compiled["contracts"][contract_path.name][contract_name]["evm"]["bytecode"]["object"]
+    return abi, bytecode
+
+
+def parse_min_profit(value: str) -> int:
+    """Parse a min-profit value specified in ether or wei."""
+    lv = value.lower().strip()
+    try:
+        if lv.endswith("ether") or lv.endswith("eth"):
+            num = lv.replace("ether", "").replace("eth", "").strip()
+            return int(Web3.to_wei(num, "ether"))
+        if lv.endswith("wei"):
+            return int(lv[:-3])
+        return int(lv)
+    except ValueError as exc:
+        raise argparse.ArgumentTypeError(
+            "--min-profit must be a number optionally followed by 'ether' or 'wei'"
+        ) from exc
+
+
+def deploy(
+    network: str,
+    pool: str,
+    min_profit_wei: int,
+    contract_path: Path,
+    gas_limit: int | None = None,
+    chain_id: int | None = None,
+):
+    """Deploy the LiquidationFlashLoan contract."""
+    env_rpc_var = f"{network.upper()}_RPC_URL"
+    load_dotenv()
+    rpc_url = os.environ.get(env_rpc_var)
+    private_key = os.environ.get("PRIVATE_KEY")
+
+    if not rpc_url:
+        raise EnvironmentError(
+            f"Missing {env_rpc_var} in environment. Check your .env file or export the variable."
+        )
+    if not private_key:
+        raise EnvironmentError(
+            "Missing PRIVATE_KEY in environment. Provide a private key in your .env file."
+        )
+
+    w3 = Web3(Web3.HTTPProvider(rpc_url))
+    account = w3.eth.account.from_key(private_key)
+    logging.info("Using account %s", account.address)
+
+    try:
+        abi, bytecode = compile_contract(contract_path)
+    except Exception as comp_err:
+        raise RuntimeError(
+            f"Compilation failed: {comp_err}. Ensure solc is installed and the contract path is correct."
+        ) from comp_err
+
+    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
+
+    nonce = w3.eth.get_transaction_count(account.address)
+
+    if chain_id is None:
+        chain_id = w3.eth.chain_id
+
+    if gas_limit is None:
+        try:
+            gas_limit = contract.constructor(pool, min_profit_wei).estimate_gas({
+                "from": account.address
+            })
+            logging.info("Estimated gas limit: %s", gas_limit)
+        except Exception as est_err:
+            raise RuntimeError(
+                "Failed to estimate gas. Specify --gas-limit or check contract parameters"
+            ) from est_err
+
+    txn = contract.constructor(pool, min_profit_wei).build_transaction({
+        "from": account.address,
+        "nonce": nonce,
+        "gasPrice": w3.eth.gas_price,
+        "gas": gas_limit,
+        "chainId": chain_id,
+    })
+
+    try:
+        signed = account.sign_transaction(txn)
+        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
+    except Exception as send_err:
+        raise RuntimeError(
+            f"Failed to send deployment transaction: {send_err}. Check gas limit and chain ID."
+        ) from send_err
+
+    logging.info("Deployment transaction sent: %s", tx_hash.hex())
+
+    try:
+        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
+    except Exception as rec_err:
+        raise RuntimeError(
+            f"Failed while waiting for receipt: {rec_err}. The transaction may have been dropped."
+        ) from rec_err
+
+    logging.info("Contract deployed at: %s", receipt.contractAddress)
+
+    output = {"address": receipt.contractAddress, "abi": abi}
+    Path("deployed_contract.json").write_text(json.dumps(output, indent=2))
+
+    return receipt.contractAddress
+
+
+if __name__ == "__main__":
+    parser = argparse.ArgumentParser(description="Deploy LiquidationFlashLoan contract")
+    parser.add_argument("--network", choices=["goerli", "sepolia"], required=True,
+                        help="Target testnet")
+    parser.add_argument("--pool", required=True, help="Pool address for constructor")
+    parser.add_argument("--min-profit", required=True,
+                        help="Minimum profit, e.g. '1ether' or '1000000000000000000 wei'")
+    parser.add_argument("--contract-path", default="contracts/LiquidationFlashLoan.sol",
+                        help="Path to Solidity contract")
+    parser.add_argument("--gas-limit", type=int, help="Gas limit for deployment")
+    parser.add_argument("--chain-id", type=int, help="Chain ID of the network")
+    args = parser.parse_args()
+
+    try:
+        address = deploy(
+            args.network,
+            args.pool,
+            parse_min_profit(args.min_profit),
+            Path(args.contract_path),
+            gas_limit=args.gas_limit,
+            chain_id=args.chain_id,
+        )
+        print(f"Deployed to: {address}")
+    except Exception as exc:
+        logging.error("Deployment failed: %s", exc)
+        if Path("deployed_contract.json").exists():
+            Path("deployed_contract.json").unlink()
+            logging.info("Cleaned up deployment artifacts")
+        raise SystemExit(1)
+
