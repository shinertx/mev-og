#!/usr/bin/env python3
"""Orchestration script for mutating strategy modules using GPT.

This script proposes minor modifications to strategy modules via the
OpenAI API, tests each mutation in a sandboxed environment, and
deploys the mutation if all tests succeed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

try:
    import openai  # type: ignore
except Exception:  # pragma: no cover - openai may not be installed
    openai = None  # fallback when openai package is unavailable

# Directory containing strategy modules
STRATEGY_DIR = Path("strategies")
# Directory to deploy successful mutations
DEPLOY_DIR = Path("deployed_strategies")
# Directory storing all mutation versions
MUTATION_DIR = Path("mutations")
# Log file for mutation history
LOG_FILE = Path("mutation_history.log")
# JSON summary for dashboards
DASHBOARD_FILE = Path("mutation_summary.json")


def load_metrics() -> dict[str, dict[str, float]]:
    """Load PnL and risk metrics from a JSON file.

    The file ``metrics.json`` should map strategy filenames to ``{"pnl": float,
    "risk": float}``. If the file is missing, an empty mapping is returned.
    """
    metrics_file = Path("metrics.json")
    if metrics_file.exists():
        try:
            return json.loads(metrics_file.read_text())
        except Exception as exc:  # pragma: no cover
            print(f"[WARN] failed to load metrics: {exc}")
            return {}
    return {}


METRICS = load_metrics()


def compute_priority(strategy: Path) -> float:
    """Return a priority score based on PnL divided by risk."""
    data = METRICS.get(strategy.name)
    if not data:
        return 0.0
    pnl = data.get("pnl", 0.0)
    risk = data.get("risk", 1.0)
    return pnl / (risk + 1e-6)


def next_version_path(strategy: Path) -> Path:
    """Return the path for the next mutation version."""
    directory = MUTATION_DIR / strategy.stem
    directory.mkdir(parents=True, exist_ok=True)
    existing = list(directory.glob("v*.py"))
    versions = [int(f.stem[1:]) for f in existing if f.stem[1:].isdigit()]
    new_version = max(versions, default=0) + 1
    return directory / f"v{new_version}.py"


def save_dashboard(data: dict) -> None:
    DASHBOARD_FILE.write_text(json.dumps(data, indent=2))


def load_dashboard() -> dict:
    if DASHBOARD_FILE.exists():
        try:
            return json.loads(DASHBOARD_FILE.read_text())
        except Exception:  # pragma: no cover
            return {}
    return {}


def log_event(strategy: Path, version: Path | None, status: str, message: str) -> None:
    """Append a log entry to the history file and update dashboard."""
    timestamp = datetime.utcnow().isoformat()
    log_entry = {
        "time": timestamp,
        "strategy": strategy.name,
        "version": version.name if version else None,
        "status": status,
        "message": message,
    }
    with LOG_FILE.open("a") as fh:
        fh.write(json.dumps(log_entry) + "\n")

    summary = load_dashboard()
    info = summary.setdefault(strategy.name, {})
    info.update({"deployed": version.name if version else info.get("deployed"), "status": status, "message": message, "time": timestamp})
    save_dashboard(summary)


def rollback(strategy: Path, version: int | None = None) -> None:
    """Rollback a deployed strategy to a previous version."""
    directory = MUTATION_DIR / strategy.stem
    if not directory.exists():
        print(f"[WARN] no versions found for {strategy}")
        return

    versions = sorted([int(p.stem[1:]) for p in directory.glob("v*.py") if p.stem[1:].isdigit()])
    if not versions:
        print(f"[WARN] no versions found for {strategy}")
        return

    target_version = version if version is not None else versions[-1]
    path = directory / f"v{target_version}.py"
    if not path.exists():
        print(f"[WARN] version {target_version} not found for {strategy}")
        return

    dest = DEPLOY_DIR / strategy.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(path, dest)
    log_event(strategy, path, "rollback", f"rolled back to version {target_version}")
    print(f"[INFO] Rolled back {strategy} to {path}")



def propose_mutation(code: str) -> str:
    """Use the GPT API to propose a minor mutation for the given code.

    If the API cannot be reached, the original code is returned.
    """
    if openai is None:
        print("[WARN] openai package not available; returning original code")
        return code

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You propose minor, backward-compatible improvements to Python "
                        "strategy modules. Only return the modified code."
                    ),
                },
                {"role": "user", "content": code},
            ],
            temperature=0.2,
        )
        mutated = response["choices"][0]["message"]["content"]
        return mutated
    except Exception as exc:  # pragma: no cover - network failure
        print(f"[WARN] GPT API request failed: {exc}; using original code")
        return code


def run_tests(path: Path) -> bool:
    """Run pytest in the provided path. Returns True on success."""
    print(f"[INFO] Running tests in {path}")
    result = subprocess.run([
        "pytest",
        "-q",
    ], cwd=path)
    return result.returncode == 0


def trigger_ci_pipeline(strategy: Path) -> None:
    """Placeholder for CI/CD integration."""
    print(f"[INFO] CI pipeline triggered for {strategy}")


def safe_check(original: str, mutated: str) -> tuple[bool, str]:
    """Perform safety checks on mutated code."""
    if original == mutated:
        return False, "mutation did not change code"
    try:
        compile(mutated, "<mutated>", "exec")
    except SyntaxError as exc:
        return False, f"syntax error: {exc}"
    return True, ""


def apply_mutation(src: Path, mutated_code: str) -> bool:
    """Apply mutation in a sandbox and test it."""
    original_code = src.read_text()
    ok, reason = safe_check(original_code, mutated_code)
    if not ok:
        print(f"[INFO] Mutation rejected for {src}: {reason}")
        log_event(src, None, "rejected", reason)
        return False

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        module_path = tmp_path / src.name
        module_path.write_text(mutated_code)

        # copy tests if present
        if Path("tests").exists():
            shutil.copytree("tests", tmp_path / "tests")

        if run_tests(tmp_path):
            dest = DEPLOY_DIR / src.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(module_path, dest)

            version_path = next_version_path(src)
            shutil.copy(module_path, version_path)

            log_event(src, version_path, "deployed", "tests passed")
            trigger_ci_pipeline(src)

            print(f"[INFO] Mutation for {src} deployed to {dest} as {version_path}")
            return True
        else:
            print(f"[INFO] Tests failed for mutation of {src}")
            log_event(src, None, "failed", "tests failed")
            return False


def mutate_strategy(strategy_file: Path) -> None:
    code = strategy_file.read_text()
    mutated = propose_mutation(code)
    apply_mutation(strategy_file, mutated)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mutate strategy modules using GPT")
    parser.add_argument(
        "--strategy",
        type=Path,
        help="Path to a specific strategy file to mutate"
    )
    parser.add_argument(
        "--rollback",
        type=Path,
        help="Rollback the specified strategy. Use --version to pick a specific version"
    )
    parser.add_argument(
        "--version",
        type=int,
        help="Version number for rollback"
    )
    parser.add_argument(
        "--schedule",
        type=int,
        help="Run continuously every N seconds"
    )
    args = parser.parse_args()

    if args.rollback:
        rollback(args.rollback, args.version)
        return

    def run_once() -> None:
        files = [args.strategy] if args.strategy else list(STRATEGY_DIR.glob("*.py"))
        if not files:
            print("[INFO] No strategy modules found to mutate")
            return

        files.sort(key=compute_priority, reverse=True)

        for f in files:
            print(f"[INFO] Processing {f}")
            mutate_strategy(f)

    if args.schedule:
        while True:
            run_once()
            time.sleep(args.schedule)
    else:
        run_once()


if __name__ == "__main__":
    main()
