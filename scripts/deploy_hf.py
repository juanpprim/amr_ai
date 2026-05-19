"""Deploy the AMR app to the Hugging Face Space via the Hub API.

Why a script instead of `git push hf`?
    The Space's git history contains an API-uploaded `data/chroma_db/` commit
    that our local repo intentionally does not track. `git push hf main`
    therefore fails with a non-fast-forward error every time the local code
    changes. Uploading via the Hub API sidesteps git entirely on the HF side:
    files we list are added/updated, files we don't touch (including
    `data/chroma_db/`) are left exactly as they are on the Space.

Usage:
    # one-time: install the deploy group
    uv sync --group deploy

    # deploy current working tree to the Space
    uv run python scripts/deploy_hf.py

    # custom repo / commit message
    uv run python scripts/deploy_hf.py \\
        --repo-id juanpprim/AMR_learning \\
        --message "deploy: fix flashcards layout"

Auth:
    Expects a token in the environment as $HF_TOKEN (preferred) or via
    `huggingface-cli login` (uses ~/.cache/huggingface/token).
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

from huggingface_hub import HfApi
from huggingface_hub.errors import HfHubHTTPError

logger = logging.getLogger(__name__)

DEFAULT_REPO_ID = "juanpprim/AMR_learning"
REPO_TYPE = "space"

# Files/directories that should never be uploaded to the Space.
# Everything under data/ is excluded so that the API-uploaded ChromaDB
# (data/chroma_db/) is preserved untouched between deploys. Re-upload the
# DB explicitly with `huggingface-cli upload <repo> data/chroma_db
# data/chroma_db --repo-type=space` when it changes.
IGNORE_PATTERNS: list[str] = [
    # VCS / dev metadata
    ".git/**",
    ".gitattributes",
    ".gitignore",
    ".github/**",
    ".vscode/**",
    ".idea/**",
    ".claude/**",
    ".cursor/**",
    # Python / build artefacts
    ".venv/**",
    "**/__pycache__/**",
    "*.py[cod]",
    "*.egg-info/**",
    "build/**",
    "dist/**",
    "wheels/**",
    # Test / lint caches
    ".pytest_cache/**",
    ".ruff_cache/**",
    ".coverage",
    "htmlcov/**",
    ".scrapy/**",
    # Secrets
    ".env",
    ".env.*",
    # Data — preserved on HF, never re-uploaded here
    "data/**",
    # Dev-only directories
    "notebook/**",
    "tests/**",
    # OS junk
    ".DS_Store",
    "**/.DS_Store",
    # Docker is not used at runtime by HF but the Dockerfile itself IS — keep it
    ".dockerignore",
]


def _current_git_sha(repo_root: Path) -> str | None:
    """Return short HEAD sha, or None if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def deploy(
    repo_id: str,
    folder: Path,
    message: str,
    token: str | None,
) -> str:
    """Upload `folder` to the HF Space, ignoring IGNORE_PATTERNS.

    Returns the commit URL.
    """
    api = HfApi(token=token)

    logger.info("Uploading %s -> %s (%s)", folder, repo_id, REPO_TYPE)
    logger.info("Excluding %d patterns (data/** preserved)", len(IGNORE_PATTERNS))

    commit_info = api.upload_folder(
        folder_path=str(folder),
        repo_id=repo_id,
        repo_type=REPO_TYPE,
        commit_message=message,
        ignore_patterns=IGNORE_PATTERNS,
    )
    return commit_info.commit_url


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--repo-id",
        default=DEFAULT_REPO_ID,
        help=f"HF Space repo id (default: {DEFAULT_REPO_ID})",
    )
    parser.add_argument(
        "--folder",
        default=".",
        type=Path,
        help="Folder to upload (default: current directory)",
    )
    parser.add_argument(
        "--message",
        default=None,
        help="Commit message (default: 'deploy: <git short sha>')",
    )
    args = parser.parse_args()

    folder = args.folder.resolve()
    if not folder.is_dir():
        logger.error("Not a directory: %s", folder)
        return 2

    token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
    if not token:
        logger.info(
            "No HF_TOKEN in env; falling back to cached credentials "
            "(`huggingface-cli login`)."
        )

    sha = _current_git_sha(folder)
    message = args.message or (
        f"deploy: {sha}" if sha else "deploy: manual upload"
    )

    try:
        commit_url = deploy(
            repo_id=args.repo_id,
            folder=folder,
            message=message,
            token=token,
        )
    except HfHubHTTPError as exc:
        logger.error("HF API error: %s", exc)
        return 1
    except Exception as exc:
        logger.error("Deploy failed: %s", exc, exc_info=True)
        return 1

    logger.info("Done. Commit: %s", commit_url)
    logger.info(
        "Space will rebuild automatically: "
        "https://huggingface.co/spaces/%s",
        args.repo_id,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
