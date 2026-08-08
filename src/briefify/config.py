import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

if ENV_FILE.exists():
    load_dotenv(ENV_FILE)


GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET_ID = os.getenv("DATASET_ID")
TABLE_ID = os.getenv("TABLE_ID")


if not all([GCP_PROJECT_ID, DATASET_ID, TABLE_ID]):
    raise ValueError(
        "Missing required environment variables: "
        "GCP_PROJECT_ID, DATASET_ID, TABLE_ID"
    )