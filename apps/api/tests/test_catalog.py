import json
import os
from pathlib import Path

import pytest
from sqlalchemy import func, select

from sliver_api.models import Dataset, Resource, SearchEvent, User
from sliver_api.seed import seed

FIXTURES = Path(__file__).parent / "fixtures" / "catalog"
PUBLIC_KEYS = {
    "id",
    "title",
    "description",
    "category",
    "tags",
    "columns",
    "row_count",
    "coverage",
    "price",
    "seller",
    "provenance",
    "content",
    "published_at",
}


@pytest.fixture
def seeded(sessions, store):
    seed(sessions, store, FIXTURES)
    return store


def search(client, **params):
    response = client.get("/api/catalog", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_seed_publishes_full_dataset_and_one_sliver_per_slice_value(seeded, sessions):
    with sessions() as db:
        titles = sorted(db.scalars(select(Resource.title)))
    assert titles == [
        "Container spot freight rates",
        "Container spot freight rates: SGSIN-CNSHA",
        "Container spot freight rates: SGSIN-IDJKT",
        "Singapore berth waiting times",
        "Singapore berth waiting times: October 2026",
        "Singapore berth waiting times: September 2026",
    ]


def test_each_sliver_is_its_own_object_containing_only_its_rows(seeded, sessions):
    with sessions() as db:
        sliver = db.scalar(select(Resource).where(Resource.title.endswith("October 2026")))
    body = seeded.get(sliver.object_key).decode()
    assert body.splitlines() == [
        "date,terminal,avg_berth_wait_hours",
        "2026-10-01,Tuas,2.8",
        "2026-10-01,Keppel,4.4",
    ]
    assert sliver.row_count == 2
    assert sliver.coverage["time"] == {"column": "date", "start": "2026-10-01", "end": "2026-10-01"}


def test_seed_is_idempotent(sessions, store):
    seed(sessions, store, FIXTURES)
    objects = dict(store.objects)
    second = seed(sessions, store, FIXTURES)
    assert second["created_resources"] == 0
    assert store.objects == objects
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.scalar(select(func.count()).select_from(Dataset)) == 2
        assert db.scalar(select(func.count()).select_from(Resource)) == 6


def test_search_ranks_relevant_resources_first(seeded, client):
    result = search(client, q="berth waiting congestion")
    assert result["total"] == 3
    assert all("berth" in item["title"].lower() for item in result["items"])
    assert result["items"][0]["relevance"] >= result["items"][-1]["relevance"]


def test_search_matches_any_term(seeded, client):
    assert search(client, q="freight helicopters")["total"] == 3


def test_filters_by_category_price_and_required_columns(seeded, client):
    assert search(client, category="freight-rates")["total"] == 3
    assert search(client, max_price_minor=200)["total"] == 2
    assert search(client, columns="lane,usd_per_container")["total"] == 3
    assert search(client, columns="lane,unknown_column")["total"] == 0


def test_pagination_is_capped(seeded, client):
    assert search(client, limit=2)["items"].__len__() == 2
    assert client.get("/api/catalog", params={"limit": 500}).status_code == 422


def test_public_responses_only_contain_allow_listed_metadata(seeded, client, sessions):
    with sessions() as db:
        private_values = [
            *db.scalars(select(Resource.object_key)),
            *db.scalars(select(Dataset.object_key)),
            *db.scalars(select(Dataset.filename)),
            *db.scalars(select(User.email)),
            "PRIVATE-RIGHTS-STATEMENT",
            "2026-10-01,Tuas,2.8",
        ]
    listing = search(client, q="berth")
    detail = client.get(f"/api/catalog/{listing['items'][0]['id']}").json()
    for item in [*listing["items"], detail]:
        assert set(item) - {"relevance"} == PUBLIC_KEYS
        assert set(item["provenance"]) <= {"source", "method", "collected_at"}
    text = json.dumps([listing, detail])
    for value in private_values:
        assert value not in text


def test_unpublished_resources_are_invisible(seeded, client, sessions):
    with sessions() as db:
        draft = db.scalar(select(Resource).where(Resource.title.endswith("SGSIN-IDJKT")))
        draft.status = "draft"
        db.commit()
        draft_id = draft.id
    assert client.get(f"/api/catalog/{draft_id}").status_code == 404
    assert search(client, category="freight-rates")["total"] == 2


def test_searches_are_recorded_and_unmet_demand_is_aggregated(seeded, client, sessions):
    search(client, q="air cargo Changi Frankfurt")
    search(client, q="Air cargo  Changi Frankfurt")
    search(client, q="berth waiting")
    search(client)  # browsing without a query is not a demand signal
    with sessions() as db:
        events = db.scalars(select(SearchEvent).order_by(SearchEvent.created_at)).all()
    assert [event.result_count for event in events] == [0, 0, 3]
    demand = client.get("/api/demand").json()["items"]
    assert demand == [
        {
            "query": "air cargo changi frankfurt",
            "searches": 2,
            "unmet_searches": 2,
            "last_seen": demand[0]["last_seen"],
        }
    ]


def test_categories_count_published_resources(seeded, client):
    assert client.get("/api/catalog/categories").json()["items"] == [
        {"category": "freight-rates", "count": 3},
        {"category": "port-operations", "count": 3},
    ]


def test_example_catalog_seeds_cleanly(sessions, store):
    explicit = os.environ.get("SLIVER_EXAMPLES_DIR")
    # In a repository checkout (CI), examples/ sits three levels above this file.
    folder = Path(explicit) if explicit else Path(__file__).resolve().parents[3] / "examples" / "datasets"
    if not (folder / "manifest.toml").exists():
        pytest.skip("example datasets are not available in this environment")
    result = seed(sessions, store, folder)
    assert result["published_resources"] == result["created_resources"] > 4
