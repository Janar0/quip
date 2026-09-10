"""Load local configuration before database and provider modules read environment."""

from pathlib import Path

from dotenv import load_dotenv

# Explicit environment variables always win over the local development file.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
