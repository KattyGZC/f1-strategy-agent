"""
Entry point para la ingesta de datos de F1.

Uso:
    poetry run python scripts/ingest.py --year 2024
    poetry run python scripts/ingest.py --year 2023 --year 2024 --year 2025
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.use_cases.ingestion.ingest_season import SeasonIngestionUseCase
from src.infrastructure.clients.openf1_client import OpenF1Client
from src.infrastructure.database.connection import SessionLocal
from src.infrastructure.storage.s3_client import S3Client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest F1 data from OpenF1 API")
    parser.add_argument(
        "--year",
        type=int,
        action="append",
        required=True,
        help="Year to ingest (can be specified multiple times)",
    )
    args = parser.parse_args()

    openf1 = OpenF1Client()
    s3 = S3Client()
    db = SessionLocal()

    try:
        use_case = SeasonIngestionUseCase(openf1=openf1, s3=s3, db=db)
        for year in sorted(set(args.year)):
            use_case.run(year)
    finally:
        db.close()


if __name__ == "__main__":
    main()
