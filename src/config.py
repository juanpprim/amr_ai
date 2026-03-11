"""Application settings loaded from environment variables.

Uses pydantic-settings to load from .env file. All configuration
is centralized here -- no hardcoded values elsewhere in the codebase.

Reference: SPEC-00, Section 3.
"""

import logging
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Typed application settings loaded from .env."""

    # PubMed / NCBI
    pubmed_api_key: str = ""
    pubmed_email: str = ""

    # Data directories
    data_raw_dir: Path = Path("./data/raw")
    data_markdown_dir: Path = Path("./data/markdown")

    # Logging
    log_level: str = "INFO"

    model_config = {"env_file": ".env"}

    def configure_logging(self) -> None:
        """Configure root logger based on settings."""
        logging.basicConfig(
            level=getattr(logging, self.log_level.upper(), logging.INFO),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
