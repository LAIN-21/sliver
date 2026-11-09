import os
import uuid

import pytest

from sliver_api.config import Settings
from sliver_api.storage import MemoryStore, ObjectExistsError, S3Store


def test_memory_store_objects_are_immutable():
    store = MemoryStore()
    store.put("datasets/a.csv", b"a,b\n1,2\n")
    with pytest.raises(ObjectExistsError):
        store.put("datasets/a.csv", b"changed")
    assert store.get("datasets/a.csv") == b"a,b\n1,2\n"


def test_s3_store_requires_credentials():
    settings = Settings(
        database_url="postgresql+psycopg://u:p@db/sliver",
        s3_endpoint_url="http://127.0.0.1:9000",
        s3_access_key_id="",
        s3_secret_access_key="",
    )
    with pytest.raises(ValueError):
        S3Store(settings)


@pytest.mark.s3
def test_s3_store_round_trip_and_immutability(settings):
    if not os.environ.get("S3_ENDPOINT_URL"):
        pytest.skip("no S3 endpoint configured")
    store = S3Store(settings)
    store.initialize()
    assert store.ready()
    key = f"tests/{uuid.uuid4()}.csv"
    try:
        store.put(key, b"a,b\n1,2\n")
        assert store.get(key) == b"a,b\n1,2\n"
        with pytest.raises(ObjectExistsError):
            store.put(key, b"overwrite")
    finally:
        store.delete(key)
