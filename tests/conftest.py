"""Shared pytest setup: load the repo's .env so tests can reach the Docker database."""

from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")
