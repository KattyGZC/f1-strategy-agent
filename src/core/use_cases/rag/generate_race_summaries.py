"""
Pipeline RAG: genera resúmenes narrativos de carreras y sus embeddings.

Flujo por cada sesión de carrera:
  1. Consulta DB → datos de laps y drivers
  2. Construye contexto estructurado (texto)
  3. Llama a Ollama → resumen narrativo
  4. Genera embedding del resumen
  5. Guarda en race_summaries (idempotente)
"""
from dataclasses import dataclass

from sqlalchemy.orm import Session as DBSession

from src.infrastructure.clients.ollama_client import OllamaClient
from src.infrastructure.database.models import Driver, Lap, Session
from src.infrastructure.database.repositories.race_summary_repo import (
    summary_exists,
    upsert_summary,
)
from src.infrastructure.database.repositories.session_repo import get_all_sessions

SYSTEM_PROMPT = (
    "You are an expert Formula 1 race analyst. "
    "Write concise, engaging race summaries in English based on the structured data provided. "
    "Focus on the winner, key battles, pit stop strategies, and any notable moments. "
    "Keep the summary between 200 and 300 words."
)


@dataclass
class SummaryResult:
    session_key: int
    circuit: str
    year: int
    skipped: bool = False
    error: str | None = None


class GenerateRaceSummariesUseCase:
    def __init__(self, db: DBSession, llm: OllamaClient) -> None:
        self._db = db
        self._llm = llm

    def run(self, year: int | None = None, force: bool = False) -> list[SummaryResult]:
        """Genera resúmenes para todas las sesiones de carrera del año dado.

        Args:
            year: Si se especifica, filtra por año. Si es None, procesa todos los años.
            force: Si True, regenera incluso si ya existe el resumen.
        """
        sessions = [
            s for s in get_all_sessions(self._db, year=year)
            if s.session_name == "Race"
        ]

        results: list[SummaryResult] = []
        for session in sessions:
            result = self._process_session(session, force=force)
            results.append(result)
        return results

    def _process_session(self, session: Session, force: bool) -> SummaryResult:
        result = SummaryResult(
            session_key=session.session_key,
            circuit=session.circuit_short_name,
            year=session.year,
        )

        if not force and summary_exists(self._db, session.session_key):
            result.skipped = True
            return result

        try:
            context = self._build_context(session)
            content = self._llm.generate(prompt=context, system=SYSTEM_PROMPT)
            embedding = self._llm.embed(content)
            upsert_summary(self._db, session.session_key, content, embedding)
        except Exception as exc:
            result.error = str(exc)

        return result

    def _build_context(self, session: Session) -> str:
        """Construye el contexto estructurado a partir de datos de la DB."""
        laps: list[Lap] = (
            self._db.query(Lap)
            .filter(Lap.session_key == session.session_key)
            .all()
        )
        drivers: list[Driver] = self._db.query(Driver).all()
        driver_map = {d.driver_number: d for d in drivers}

        # Agrega stats por piloto
        stats: dict[int, dict] = {}
        for lap in laps:
            num = lap.driver_number
            if num not in stats:
                stats[num] = {"laps": 0, "pit_stops": 0, "best_ms": None}
            stats[num]["laps"] += 1
            if lap.is_pit_out_lap:
                stats[num]["pit_stops"] += 1
            if lap.duration_ms and not lap.is_pit_out_lap:
                if stats[num]["best_ms"] is None or lap.duration_ms < stats[num]["best_ms"]:
                    stats[num]["best_ms"] = lap.duration_ms

        lines = [
            f"F1 Race: {session.circuit_short_name} {session.year}",
            f"Date: {session.date_start.date() if session.date_start else 'unknown'}",
            "",
            "Driver Stats:",
        ]
        for num, s in sorted(stats.items(), key=lambda x: -x[1]["laps"]):
            driver = driver_map.get(num)
            name = driver.full_name if driver else f"#{num}"
            team = driver.team_name if driver else "unknown"
            best = f"{s['best_ms'] / 1000:.3f}s" if s["best_ms"] else "n/a"
            lines.append(
                f"  - #{num} {name} ({team}): "
                f"{s['laps']} laps, {s['pit_stops']} pit stops, fastest lap: {best}"
            )

        return "\n".join(lines)
