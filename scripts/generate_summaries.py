"""
CLI para generar resúmenes de carrera + embeddings con Ollama.

Uso:
    poetry run python scripts/generate_summaries.py
    poetry run python scripts/generate_summaries.py --year 2024
    poetry run python scripts/generate_summaries.py --year 2024 --force
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.use_cases.rag.generate_race_summaries import GenerateRaceSummariesUseCase
from src.infrastructure.clients.ollama_client import OllamaClient
from src.infrastructure.database.connection import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate F1 race summaries with Ollama")
    parser.add_argument("--year", type=int, default=None, help="Filter by year (e.g. 2024)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate summaries even if they already exist",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        llm = OllamaClient()
        use_case = GenerateRaceSummariesUseCase(db=db, llm=llm)

        label = f"year={args.year}" if args.year else "all years"
        print(f"Generating race summaries ({label})...")

        results = use_case.run(year=args.year, force=args.force)

        generated = sum(1 for r in results if not r.skipped and not r.error)
        skipped = sum(1 for r in results if r.skipped)
        errors = [r for r in results if r.error]

        for r in results:
            if r.skipped:
                print(f"  [skip]  {r.year} {r.circuit}")
            elif r.error:
                print(f"  [error] {r.year} {r.circuit} → {r.error}")
            else:
                print(f"  [ok]    {r.year} {r.circuit}")

        print(f"\nDone: {generated} generated, {skipped} skipped, {len(errors)} errors.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
