import copy
from datetime import date

import pytest

from conftest import LISTINGS
from sliver_mcp.evaluate import evaluate, terms

TODAY = date(2026, 11, 9)


def run(need, listings=LISTINGS, **criteria):
    defaults = {
        "required_columns": [],
        "required_terms": [],
        "time_start": None,
        "time_end": None,
        "max_age_days": None,
        "budget_minor": 500,
    }
    return evaluate(copy.deepcopy(listings), need=need, today=TODAY, **(defaults | criteria))


def test_a_need_the_catalog_does_not_cover_gets_look_elsewhere():
    report = run("air-cargo rates Changi to Frankfurt", required_columns=["origin", "destination"])
    assert report["recommendation"] == "look_elsewhere" and report["best"] is None
    assert all(candidate["verdict"] == "look_elsewhere" for candidate in report["candidates"])
    assert "Nothing on Sliver covers this need" in report["summary"]
    assert report["spent"] == 0


def test_a_covered_need_within_budget_gets_buy():
    report = run(
        "container spot freight rates from Singapore",
        required_columns=["week_start", "usd_per_container"],
        required_terms=["CNSHA"],
        time_start="2026-09",
        time_end="2026-10",
    )
    assert report["recommendation"] == "buy"
    best = report["candidates"][0]
    assert best["resource_id"] == LISTINGS[0]["id"] and best["verdict"] == "buy"
    assert best["column_coverage"] == 1 and best["time_overlap"] == 0.918  # 56 of 61 days


def test_over_budget_is_skip_and_says_to_ask_the_human():
    report = run("singapore berth waiting times", budget_minor=500)
    assert report["recommendation"] == "skip"
    assert any("ask your human" in reason for reason in report["candidates"][0]["reasons"])


def test_no_budget_is_skip():
    report = run("container spot freight rates", budget_minor=None)
    assert report["recommendation"] == "skip"
    assert "no budget given" in report["summary"]


def test_missing_columns_mean_look_elsewhere():
    report = run("container spot freight rates", required_columns=["transit_days"])
    assert report["recommendation"] == "look_elsewhere"
    freight = next(c for c in report["candidates"] if c["resource_id"] == LISTINGS[0]["id"])
    assert "missing required columns: transit_days" in freight["reasons"]


def test_a_time_range_outside_coverage_means_look_elsewhere():
    report = run("container spot freight rates", time_start="2025-01", time_end="2025-06")
    assert report["recommendation"] == "look_elsewhere"


def test_stale_data_is_skip():
    report = run("container spot freight rates", max_age_days=7)
    assert report["recommendation"] == "skip"
    assert any("older than the 7-day limit" in reason for reason in report["candidates"][0]["reasons"])


def test_evaluation_is_deterministic():
    assert run("container freight rates") == run("container freight rates")


def test_terms_ignore_stopwords_and_plurals():
    assert terms("The rates for containers from Singapore") == ["rate", "container", "singapore"]


def test_an_invalid_requested_time_range_is_a_clear_error():
    with pytest.raises(ValueError, match="time_start must be YYYY, YYYY-MM or YYYY-MM-DD"):
        run("container spot freight rates", time_start="2026-13")


def test_malformed_listing_metadata_is_a_gap_not_a_crash():
    broken = copy.deepcopy(LISTINGS)
    broken[0]["coverage"]["time"] = {"start": "last summer", "end": "2026-10-26"}
    broken[1]["columns"].append({"type": "text"})
    report = run("container spot freight rates", listings=broken, time_start="2026-09")
    freight = next(c for c in report["candidates"] if c["resource_id"] == LISTINGS[0]["id"])
    assert freight["verdict"] == "look_elsewhere"
    assert "no readable time coverage to compare with the requested range" in freight["reasons"]
    assert len(report["candidates"]) == len(LISTINGS)
