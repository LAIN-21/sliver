import os
import threading
from datetime import timedelta
from pathlib import Path

import pytest
from accounts import make_user, sign_in
from sqlalchemy import select, update
from test_catalog import FIXTURES
from test_seller import upload

from sliver_api.models import Dataset, PipelineStep, utcnow
from sliver_api.pipeline import privacy
from sliver_api.pipeline.jobs import MAX_ATTEMPTS, claim_next, execute, process_available
from sliver_api.pipeline.table import looks_like_formula
from sliver_api.pipeline.validate import inspect_csv
from sliver_api.seed import seed
from sliver_api.worker import work

TIMEOUT = 300


def codes(result) -> list[str]:
    return [item["code"] for item in result.findings]


# --- validate -----------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["-12", "-0.75", "+3", "-1e3", "-1,234.50", "-5%", "-", "+"])
def test_signed_numbers_are_not_spreadsheet_formulas(value):
    assert not looks_like_formula(value)


@pytest.mark.parametrize("value", ["=SUM(A1:A2)", "+cmd|' /C calc'!A0", "-2+3", "@SUM(1)", " =1", "\t=1"])
def test_formula_like_cells_are_flagged(value):
    assert looks_like_formula(value)


def test_negative_numbers_pass_validation_cleanly():
    result = inspect_csv(b"day,change\n2026-10-01,-12.5\n2026-10-02,+3\n2026-10-03,-1e3\n")
    assert result.status == "passed", result.findings
    assert result.dataset_updates == {"row_count": 3}


def test_formulas_in_header_cells_fail_validation():
    result = inspect_csv(b'lane,=HYPERLINK("http://x")\nA,1\n')
    assert result.status == "failed"
    assert codes(result) == ["spreadsheet_formula_header"]


def test_formulas_in_data_cells_are_a_warning_with_rows():
    result = inspect_csv(b"lane,value\nA,=1+1\nB,2\nC,@cmd\n")
    assert result.status == "warning"
    [item] = result.findings
    assert item["code"] == "spreadsheet_formula" and item["rows"] == [1, 3] and item["column"] == "value"


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "empty_file"),
        ("name\nJos\xe9\n".encode("latin-1"), "encoding"),
        (b"a,b\n1,\x002\n", "null_byte"),
        (b"a,b\n", "no_rows"),
        (b"a,a\n1,2\n", "duplicate_header"),
        (b"a,,c\n1,2,3\n", "empty_header"),
        (b"a,b\n1,2\n3\n4,5,6\n", "row_width"),
        (b'a,b\n"unterminated,2\n', "syntax"),
        (b"\n1,2\n", "no_header"),
    ],
)
def test_invalid_csvs_fail_with_a_clear_issue(data, code):
    result = inspect_csv(data)
    assert result.status == "failed"
    assert code in codes(result)
    assert all(item["message"] for item in result.findings)


def test_row_width_issues_name_the_rows():
    result = inspect_csv(b"a,b\n1,2\n3\n4,5,6\n7,8\n")
    [item] = result.findings
    assert item["rows"] == [2, 3] and "rows 2, 3" in item["message"]


def test_soft_quality_issues_are_low_severity_warnings():
    result = inspect_csv(b"a,b\n1,\n1,\n")
    assert result.status == "warning"
    assert sorted(codes(result)) == ["duplicate_rows", "missing_values"]


# --- privacy ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cell", "code"),
    [
        ("ops@example.com", "email"),
        ("+65 6123 4567", "phone"),
        ("9123 4567", "phone"),
        ("555-123-4567", "phone"),
        ("4111 1111 1111 1111", "card_number"),
        ("5555-5555-5555-4444", "card_number"),
        ("GB82 WEST 1234 5698 7654 32", "iban"),
        ("DE89370400440532013000", "iban"),
        ("S1234567D", "nric_fin"),
        ("G7654321X", "nric_fin"),
    ],
)
def test_personal_data_values_are_detected(cell, code):
    assert code in privacy.scan_column([cell])


@pytest.mark.parametrize(
    "cell",
    [
        "4111 1111 1111 1112",  # fails Luhn
        "GB00 WEST 1234 5698 7654 32",  # fails the IBAN checksum
        "1700000000000",  # epoch milliseconds
        "2026-10-01",
        "-1234.5678",
        "12345678",  # bare digits are not assumed to be phone numbers
        "Pasir Panjang",
        "X1234567D",
    ],
)
def test_ordinary_values_are_not_flagged(cell):
    assert privacy.scan_column([cell]) == {}


@pytest.mark.parametrize(
    ("name", "severity"),
    [
        ("customer_email", "low"),
        ("Phone Number", "low"),
        ("contact_name", "low"),
        ("nric", "medium"),
        ("holderPassportNumber", "medium"),
        ("card_number", "medium"),
        ("terminal_name", None),
        ("vessel_class", None),
        ("avg_berth_wait_hours", None),
    ],
)
def test_sensitive_column_names(name, severity):
    assert privacy.sensitive_name(name) == severity


# --- worker, ordering and claiming --------------------------------------------------------


@pytest.fixture
def seller(make_client, sessions):
    make_user(sessions, "seller@example.test")
    client = make_client()
    sign_in(client, "seller@example.test")
    return client


def steps(sessions, dataset_id):
    with sessions() as db:
        return db.execute(
            select(PipelineStep.stage, PipelineStep.status)
            .where(PipelineStep.dataset_id == dataset_id)
            .order_by(PipelineStep.position)
        ).all()


def detail(client, dataset_id):
    return client.get(f"/api/seller/datasets/{dataset_id}").json()


def test_worker_runs_stages_in_order(seller, sessions, store):
    dataset_id = upload(seller).json()["id"]
    order = []
    while (step_id := claim_next(sessions, TIMEOUT)) is not None:
        with sessions() as db:
            order.append(db.get(PipelineStep, step_id).stage)
        execute(sessions, store, step_id)
    assert order == ["validate", "profile", "privacy", "duplicates"]
    assert detail(seller, dataset_id)["status"] == "review"


def test_a_later_stage_is_not_claimable_while_an_earlier_one_runs(seller, sessions):
    upload(seller)
    first = claim_next(sessions, TIMEOUT)
    assert first is not None
    assert claim_next(sessions, TIMEOUT) is None  # profile waits for validate


def test_concurrent_workers_claim_different_datasets(seller, sessions, engine):
    ids = [upload(seller, title=f"Dataset {n}").json()["id"] for n in range(2)]
    claimed: list[str] = []
    barrier = threading.Barrier(2)

    def claim():
        barrier.wait()
        claimed.append(claim_next(sessions, TIMEOUT))

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    with sessions() as db:
        claimed_datasets = {db.get(PipelineStep, step_id).dataset_id for step_id in claimed if step_id}
    assert claimed_datasets == set(ids)


def test_claiming_uses_skip_locked(seller, sessions):
    upload(seller)
    with sessions() as db, db.begin():
        # Another worker holds the only pending step's row lock.
        db.execute(select(PipelineStep).where(PipelineStep.stage == "validate").with_for_update())
        assert claim_next(sessions, TIMEOUT) is None
    assert claim_next(sessions, TIMEOUT) is not None


def test_failed_validation_skips_later_stages_and_rejects(seller, sessions, store):
    dataset_id = upload(seller, body=b"a,b\n1\n").json()["id"]
    process_available(sessions, store, TIMEOUT)
    assert steps(sessions, dataset_id) == [
        ("validate", "failed"),
        ("profile", "skipped"),
        ("privacy", "skipped"),
        ("duplicates", "skipped"),
    ]
    body = detail(seller, dataset_id)
    assert body["status"] == "rejected"
    assert body["steps"][0]["findings"][0]["code"] == "row_width"


def test_abandoned_steps_are_reclaimed_then_given_up(seller, sessions, store):
    dataset_id = upload(seller).json()["id"]
    step_id = claim_next(sessions, TIMEOUT)
    stale = utcnow() - timedelta(seconds=TIMEOUT + 1)
    with sessions() as db, db.begin():
        db.execute(update(PipelineStep).where(PipelineStep.id == step_id).values(started_at=stale))
    assert claim_next(sessions, TIMEOUT) == step_id
    with sessions() as db, db.begin():
        db.execute(
            update(PipelineStep)
            .where(PipelineStep.id == step_id)
            .values(started_at=stale, attempts=MAX_ATTEMPTS)
        )
    assert claim_next(sessions, TIMEOUT) == step_id
    assert execute(sessions, store, step_id) == "failed"
    assert steps(sessions, dataset_id)[1:] == [
        ("profile", "skipped"),
        ("privacy", "skipped"),
        ("duplicates", "skipped"),
    ]


def test_tampered_objects_fail_the_stage(seller, sessions, store):
    dataset_id = upload(seller).json()["id"]
    with sessions() as db:
        key = db.get(Dataset, dataset_id).object_key
    store.objects[key] = b"tampered,data\n1,2\n"
    process_available(sessions, store, TIMEOUT)
    body = detail(seller, dataset_id)
    assert body["steps"][0]["error"] == "Stored bytes do not match the upload's SHA-256."
    assert body["status"] == "rejected"


def test_stage_crashes_are_recorded_without_stopping_the_pipeline(seller, sessions, store, monkeypatch):
    from sliver_api.pipeline import registry

    def boom(_context):
        raise RuntimeError("bug")

    stages = {**registry.STAGES_BY_NAME}
    stages["privacy"] = registry.Stage("privacy", "Privacy scan", boom)
    monkeypatch.setattr("sliver_api.pipeline.jobs.STAGES_BY_NAME", stages)
    dataset_id = upload(seller).json()["id"]
    process_available(sessions, store, TIMEOUT)
    assert [status for _, status in steps(sessions, dataset_id)] == ["passed", "passed", "failed", "passed"]
    assert detail(seller, dataset_id)["steps"][2]["error"].startswith("The stage could not finish")


def test_worker_loop_writes_heartbeat_and_drains_jobs(seller, settings, engine, store, sessions, tmp_path):
    settings = settings.model_copy(update={"worker_heartbeat_path": str(tmp_path / "beat")})
    dataset_id = upload(seller).json()["id"]
    while work(settings, engine, store):
        pass
    assert (tmp_path / "beat").exists()
    assert {status for _, status in steps(sessions, dataset_id)} == {"passed"}


# --- privacy and duplicates end to end -----------------------------------------------------


PII = (
    b"customer_name,email,phone,card,iban,nric,city\n"
    b"Tan Wei Ming,wei@example.com,+65 6123 4567,4111 1111 1111 1111,"
    b"GB82 WEST 1234 5698 7654 32,S1234567D,SG\n"
)


def test_privacy_findings_carry_severity_and_never_the_values(seller, sessions, store):
    dataset_id = upload(seller, body=PII).json()["id"]
    process_available(sessions, store, TIMEOUT)
    body = detail(seller, dataset_id)
    privacy_step = next(step for step in body["steps"] if step["stage"] == "privacy")
    assert privacy_step["status"] == "failed"
    found = {(item["code"], item.get("column")): item["severity"] for item in privacy_step["findings"]}
    assert found[("email", "email")] == "medium"
    assert found[("phone", "phone")] == "medium"
    assert found[("card_number", "card")] == "high"
    assert found[("iban", "iban")] == "high"
    assert found[("nric_fin", "nric")] == "high"
    assert found[("sensitive_column_name", "customer_name")] == "low"
    assert found[("sensitive_column_name", "nric")] == "medium"
    text = str(privacy_step)
    for secret in ("wei@example.com", "4111", "GB82", "S1234567D", "6123"):
        assert secret not in text
    assert body["status"] == "rejected"


@pytest.fixture
def catalog(sessions, store):
    seed(sessions, store, FIXTURES)


def test_exact_duplicate_of_a_published_dataset_is_detected(catalog, seller, sessions, store):
    original = (FIXTURES / "rates.csv").read_bytes()
    dataset_id = upload(seller, body=original, title="Spot rates copy").json()["id"]
    process_available(sessions, store, TIMEOUT)
    step = detail(seller, dataset_id)["steps"][3]
    assert step["status"] == "failed"
    [item] = step["findings"]
    assert item["code"] == "exact_duplicate" and item["severity"] == "high"
    assert "Container spot freight rates" in item["message"]  # the public listing title
    assert "matched_dataset" not in item  # another seller's dataset id stays private


def test_near_duplicate_of_a_published_dataset_is_detected(catalog, seller, sessions, store):
    lines = (FIXTURES / "rates.csv").read_text().splitlines()
    header, rows = lines[0], lines[1:]
    reordered = "\n".join([header, *reversed(rows)]) + "\n"
    dataset_id = upload(seller, body=reordered.encode(), title="Spot rates reordered").json()["id"]
    process_available(sessions, store, TIMEOUT)
    step = detail(seller, dataset_id)["steps"][3]
    assert step["status"] == "warning"
    [item] = step["findings"]
    assert item["code"] == "near_duplicate" and item["row_overlap"] == 1.0


def test_unrelated_data_and_private_uploads_of_others_are_not_duplicates(
    catalog, seller, make_client, sessions, store
):
    make_user(sessions, "other@example.test")
    other = make_client()
    sign_in(other, "other@example.test")
    body = b"sensor,reading\nA,1\nB,2\nC,3\n"
    upload(other, body=body + b"D,4\n", title="Other private")
    process_available(sessions, store, TIMEOUT)
    dataset_id = upload(seller, body=body, title="Mine").json()["id"]
    process_available(sessions, store, TIMEOUT)
    step = detail(seller, dataset_id)["steps"][3]
    assert step["status"] == "passed", step["findings"]


def test_own_earlier_upload_is_linked_as_a_duplicate(seller, sessions, store):
    first = upload(seller).json()["id"]
    process_available(sessions, store, TIMEOUT)
    second = upload(seller, title="Same again").json()["id"]
    process_available(sessions, store, TIMEOUT)
    [item] = detail(seller, second)["steps"][3]["findings"]
    assert item["code"] == "exact_duplicate" and item["matched_dataset"] == first
    assert "Terminal waits" in item["message"]


def examples_folder() -> Path | None:
    explicit = os.environ.get("SLIVER_EXAMPLES_DIR")
    datasets = Path(explicit) if explicit else Path(__file__).resolve().parents[3] / "examples" / "datasets"
    return datasets if (datasets.parent / "seller").exists() else None


def test_example_seller_fixtures(seller, sessions, store):
    folder = examples_folder()
    if folder is None:
        pytest.skip("example datasets are not available in this environment")
    seed(sessions, store, folder)
    results = {}
    for name in ("customer-contacts-pii", "spot-rates-relisted", "invalid-quality"):
        body = (folder.parent / "seller" / f"{name}.csv").read_bytes()
        results[name] = upload(seller, body=body, title=name).json()["id"]
    exact = upload(seller, body=(folder / "sg-berth-waiting-times.csv").read_bytes(), title="exact").json()[
        "id"
    ]
    process_available(sessions, store, TIMEOUT)

    pii = {step["stage"]: step for step in detail(seller, results["customer-contacts-pii"])["steps"]}
    assert {"email", "phone", "card_number", "iban", "nric_fin"} <= {
        f["code"] for f in pii["privacy"]["findings"]
    }
    near = detail(seller, results["spot-rates-relisted"])["steps"][3]["findings"]
    assert [item["code"] for item in near] == ["near_duplicate"]
    invalid = detail(seller, results["invalid-quality"])["steps"][0]
    assert {"spreadsheet_formula_header", "row_width"} <= {f["code"] for f in invalid["findings"]}
    assert detail(seller, exact)["steps"][3]["findings"][0]["code"] == "exact_duplicate"


def test_storage_outages_leave_the_step_for_a_retry(seller, sessions, store, monkeypatch):
    dataset_id = upload(seller).json()["id"]

    def unavailable(_key):
        raise ConnectionError("storage down")

    monkeypatch.setattr(store, "get", unavailable)
    step_id = claim_next(sessions, TIMEOUT)
    assert execute(sessions, store, step_id) == "running"
    assert claim_next(sessions, TIMEOUT) is None  # not retried before the timeout
    monkeypatch.undo()
    with sessions() as db, db.begin():
        stale = utcnow() - timedelta(seconds=TIMEOUT + 1)
        db.execute(update(PipelineStep).where(PipelineStep.id == step_id).values(started_at=stale))
    process_available(sessions, store, TIMEOUT)
    assert {status for _, status in steps(sessions, dataset_id)} == {"passed"}
