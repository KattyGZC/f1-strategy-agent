from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from src.infrastructure.database.models import RaceSummary


def search_similar_summaries(
    db: Session, query_embedding: list[float], top_k: int = 3
) -> list[RaceSummary]:
    """Retorna los top_k resúmenes más similares usando distancia coseno (pgvector)."""
    return list(
        db.scalars(
            select(RaceSummary)
            .where(RaceSummary.embedding.is_not(None))
            .order_by(RaceSummary.embedding.cosine_distance(query_embedding))
            .limit(top_k)
        )
    )


def summary_exists(db: Session, session_key: int) -> bool:
    return (
        db.scalar(select(exists().where(RaceSummary.session_key == session_key))) or False
    )


def upsert_summary(
    db: Session, session_key: int, content: str, embedding: list[float]
) -> RaceSummary:
    existing = db.scalar(
        select(RaceSummary).where(RaceSummary.session_key == session_key)
    )
    if existing:
        existing.content = content
        existing.embedding = embedding
        db.commit()
        db.refresh(existing)
        return existing

    summary = RaceSummary(session_key=session_key, content=content, embedding=embedding)
    db.add(summary)
    db.commit()
    db.refresh(summary)
    return summary
