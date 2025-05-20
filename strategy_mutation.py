"""Orchestration script for automated MEV strategy mutation using OpenAI GPT.

This script generates code mutations via OpenAI's GPT models, applies them in a
sandboxed git environment, runs tests, compares results with the baseline, and
promotes successful changes. The workflow is suitable for CI/CD pipelines.
"""

import argparse
import logging
import os
import subprocess
import tempfile
from datetime import datetime

import openai


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_tests(repo_path: str) -> tuple[bool, str]:
    """Run unit and integration tests using pytest.

    Returns a tuple of success flag and combined output.
    """
    logger.info("Running tests in %s", repo_path)
    result = subprocess.run(
        ["pytest", "-q"], cwd=repo_path, capture_output=True, text=True
    )
    success = result.returncode == 0
    logger.info("Tests %s", "passed" if success else "failed")
    return success, result.stdout + result.stderr


def get_current_commit(repo_path: str) -> str:
    """Return the current git commit hash for rollback."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_path, capture_output=True, text=True
    )
    return result.stdout.strip()


def checkout_commit(repo_path: str, commit: str) -> None:
    """Checkout the specified commit, discarding local changes."""
    subprocess.run(["git", "reset", "--hard", commit], cwd=repo_path, check=True)


def apply_patch(repo_path: str, patch: str) -> bool:
    """Apply a unified diff patch to the repository."""
    with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
        tmp.write(patch)
        tmp_path = tmp.name
    result = subprocess.run(
        ["git", "apply", tmp_path], cwd=repo_path, capture_output=True, text=True
    )
    os.unlink(tmp_path)
    if result.returncode != 0:
        logger.error("Patch failed: %s", result.stderr)
        return False
    logger.info("Patch applied successfully")
    return True


def generate_mutation(prompt: str, model: str = "gpt-4") -> str:
    """Use OpenAI API to generate a code mutation patch."""
    logger.info("Requesting mutation from OpenAI")
    response = openai.ChatCompletion.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    patch = response.choices[0].message.content
    logger.debug("Received patch:\n%s", patch)
    return patch


def main() -> None:
    parser = argparse.ArgumentParser(description="MEV strategy mutation orchestrator")
    parser.add_argument("repo", help="Path to git repository to mutate")
    parser.add_argument("--openai-key", help="OpenAI API key", required=True)
    parser.add_argument(
        "--model", default="gpt-4", help="OpenAI model for generating mutations"
    )
    args = parser.parse_args()

    openai.api_key = args.openai_key
    repo_path = os.path.abspath(args.repo)

    if not os.path.isdir(os.path.join(repo_path, ".git")):
        logger.error("%s is not a git repository", repo_path)
        return

    baseline_commit = get_current_commit(repo_path)
    logger.info("Baseline commit %s", baseline_commit)

    success, baseline_output = run_tests(repo_path)
    if not success:
        logger.error("Baseline tests are failing. Aborting mutation process.")
        return

    # Prepare mutation prompt with baseline results
    mutation_prompt = (
        "Improve MEV and flash loan strategies. Provide a git patch with your "
        "changes. Ensure the patch applies cleanly and keeps tests passing."
    )

    patch = generate_mutation(mutation_prompt, args.model)

    if not apply_patch(repo_path, patch):
        checkout_commit(repo_path, baseline_commit)
        return

    mut_success, mut_output = run_tests(repo_path)

    if mut_success:
        logger.info("Mutation tests passed. Committing changes.")
        subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True)
        commit_msg = f"Automated mutation: {datetime.utcnow().isoformat()}"
        subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo_path, check=True)
        logger.info("Mutation committed successfully")
    else:
        logger.error("Mutation tests failed. Rolling back.")
        checkout_commit(repo_path, baseline_commit)

    # Log outputs for review
    log_dir = os.path.join(repo_path, "mutation_logs")
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    with open(os.path.join(log_dir, f"baseline_{timestamp}.log"), "w") as f:
        f.write(baseline_output)
    with open(os.path.join(log_dir, f"mutation_{timestamp}.log"), "w") as f:
        f.write(mut_output)


if __name__ == "__main__":
    main()
