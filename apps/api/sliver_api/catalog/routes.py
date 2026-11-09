from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from ..deps import DB
from .search import MAX_PAGE_SIZE, CatalogQuery, get_published, list_categories, search_catalog, unmet_demand

router = APIRouter(prefix="/api", tags=["catalog"])


@router.get("/catalog")
def catalog(
    db: DB,
    q: Annotated[str, Query(max_length=300)] = "",
    category: Annotated[str | None, Query(max_length=60)] = None,
    max_price_minor: Annotated[int | None, Query(gt=0, le=100_000_000)] = None,
    columns: Annotated[str | None, Query(max_length=1000, description="Comma-separated column names")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> dict:
    required = [name.strip() for name in (columns or "").split(",") if name.strip()]
    return search_catalog(
        db,
        CatalogQuery(
            q=q,
            category=category,
            max_price_minor=max_price_minor,
            columns=required[:20],
            limit=limit,
            offset=offset,
        ),
    )


@router.get("/catalog/categories")
def categories(db: DB) -> dict:
    return {"items": list_categories(db)}


@router.get("/catalog/{resource_id}")
def resource_detail(resource_id: Annotated[str, Path(max_length=36)], db: DB) -> dict:
    found = get_published(db, resource_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return found


@router.get("/demand")
def demand(
    db: DB,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict:
    return {"days": days, "items": unmet_demand(db, days, limit)}
