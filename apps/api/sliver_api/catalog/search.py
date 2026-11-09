"""Catalog queries over published Resources, plus anonymous demand signals."""

import re
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import Select, Text, case, func, select
from sqlalchemy.orm import Session

from ..models import Dataset, Resource, SearchEvent, User, utcnow
from .public import public_resource

MAX_PAGE_SIZE = 50


@dataclass
class CatalogQuery:
    q: str = ""
    category: str | None = None
    max_price_minor: int | None = None
    columns: list[str] = field(default_factory=list)
    limit: int = 20
    offset: int = 0


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _published() -> Select:
    return (
        select(Resource, User.display_name, Dataset.provenance)
        .join(User, Resource.owner_id == User.id)
        .join(Dataset, Resource.dataset_id == Dataset.id)
        .where(Resource.status == "published")
    )


def _any_term(q: str):
    # Agents describe needs in many words; match any of them and rank by relevance.
    return func.to_tsquery("english", func.replace(func.plainto_tsquery("english", q).cast(Text), "&", "|"))


def count_text_matches(db: Session, q: str) -> int:
    statement = _published().where(Resource.search_vector.op("@@")(_any_term(q)))
    return db.scalar(select(func.count()).select_from(statement.subquery())) or 0


def search_catalog(db: Session, query: CatalogQuery) -> dict:
    statement = _published()
    rank = None
    if query.q.strip():
        any_term = _any_term(query.q)
        rank = func.ts_rank_cd(Resource.search_vector, any_term)
        statement = statement.where(Resource.search_vector.op("@@")(any_term))
    if query.category:
        statement = statement.where(Resource.category == query.category.lower())
    if query.max_price_minor is not None:
        statement = statement.where(Resource.price_minor <= query.max_price_minor)
    if query.columns:
        statement = statement.where(Resource.column_names.contains([c.lower() for c in query.columns]))

    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    if rank is not None:
        statement = statement.add_columns(rank.label("rank")).order_by(rank.desc(), Resource.id)
    else:
        statement = statement.order_by(Resource.published_at.desc(), Resource.id)
    limit = max(1, min(query.limit, MAX_PAGE_SIZE))
    rows = db.execute(statement.limit(limit).offset(max(0, query.offset))).all()

    items, top_score = [], 0.0
    for row in rows:
        resource, seller_name, provenance = row[0], row[1], row[2]
        item = public_resource(resource, seller_name, provenance)
        if rank is not None:
            item["relevance"] = round(float(row[3]), 4)
            top_score = max(top_score, item["relevance"])
        items.append(item)

    if query.q.strip() and query.offset == 0:
        # Demand reflects what the text asked for: a miss caused only by filters (price, category,
        # columns) is not unmet demand, so record how many Resources match the text alone.
        filtered = query.category or query.max_price_minor is not None or query.columns
        text_matches = total if total or not filtered else count_text_matches(db, query.q)
        record_search(db, query, text_matches, top_score)
    return {"items": items, "total": total, "limit": limit, "offset": max(0, query.offset)}


def record_search(db: Session, query: CatalogQuery, result_count: int, top_score: float) -> None:
    filters = {
        key: value
        for key, value in {
            "category": query.category,
            "max_price_minor": query.max_price_minor,
            "columns": query.columns or None,
        }.items()
        if value is not None
    }
    db.add(
        SearchEvent(
            query=query.q.strip()[:300],
            normalized_query=normalize(query.q)[:300],
            filters=filters,
            result_count=result_count,
            top_score=top_score,
        )
    )
    db.commit()


def get_published(db: Session, resource_id: str) -> dict | None:
    row = db.execute(_published().where(Resource.id == resource_id)).first()
    return public_resource(row[0], row[1], row[2]) if row else None


def list_categories(db: Session) -> list[dict]:
    rows = db.execute(
        select(Resource.category, func.count())
        .where(Resource.status == "published")
        .group_by(Resource.category)
        .order_by(Resource.category)
    ).all()
    return [{"category": category, "count": count} for category, count in rows]


def unmet_demand(db: Session, days: int, limit: int) -> list[dict]:
    """Queries that found nothing: what agents wanted and the catalog could not supply."""
    unmet = func.sum(case((SearchEvent.result_count == 0, 1), else_=0))
    rows = db.execute(
        select(
            SearchEvent.normalized_query,
            func.count().label("searches"),
            unmet.label("unmet"),
            func.max(SearchEvent.created_at).label("last_seen"),
        )
        .where(SearchEvent.created_at >= utcnow() - timedelta(days=days))
        .group_by(SearchEvent.normalized_query)
        .having(unmet > 0)
        .order_by(unmet.desc(), func.max(SearchEvent.created_at).desc())
        .limit(limit)
    ).all()
    return [
        {
            "query": query,
            "searches": searches,
            "unmet_searches": unmet_count,
            "last_seen": last_seen.isoformat().replace("+00:00", "Z"),
        }
        for query, searches, unmet_count, last_seen in rows
    ]
