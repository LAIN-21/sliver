import pytest
from accounts import PASSWORD, make_user, sign_in
from sqlalchemy import func, select
from test_catalog import FIXTURES

from sliver_api.auth.passwords import hash_password, verify_password
from sliver_api.auth.service import COOKIE_NAME, REVIEWER_EMAIL, token_id
from sliver_api.models import AuthSession, User
from sliver_api.seed import seed


def test_scrypt_hashes_are_salted_and_verify():
    first, second = hash_password("s3cret"), hash_password("s3cret")
    assert first.startswith("scrypt$16384$8$1$") and first != second
    assert verify_password("s3cret", first)
    assert not verify_password("wrong", first)
    assert not verify_password("s3cret", None)
    assert not verify_password("s3cret", "plain-text")
    with pytest.raises(ValueError):
        hash_password("")


def test_login_sets_an_httponly_samesite_cookie_backed_by_a_stored_session(make_client, sessions):
    make_user(sessions, "seller@example.test")
    client = make_client()
    response = sign_in(client, "Seller@Example.test")
    cookie = response.headers["set-cookie"]
    assert f"{COOKIE_NAME}=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert response.json()["user"]["role"] == "seller"
    assert "password_hash" not in response.json()["user"]
    token = client.cookies[COOKIE_NAME]
    with sessions() as db:
        stored = db.scalars(select(AuthSession.id)).all()
    # Only the token's hash is persisted.
    assert stored == [token_id(token)] and token not in stored
    assert client.get("/api/auth/me").json()["user"]["email"] == "seller@example.test"


@pytest.mark.parametrize(
    ("email", "password"),
    [("seller@example.test", "wrong password"), ("nobody@example.test", PASSWORD)],
)
def test_bad_credentials_are_refused_with_one_message(make_client, sessions, email, password):
    make_user(sessions, "seller@example.test")
    response = make_client().post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 401
    assert response.json() == {"detail": "Email or password is incorrect."}


def test_accounts_without_a_password_cannot_sign_in(make_client, sessions):
    make_user(sessions, "seed-only@example.test", password=None)
    response = make_client().post(
        "/api/auth/login", json={"email": "seed-only@example.test", "password": "x"}
    )
    assert response.status_code == 401


def test_logout_ends_the_server_side_session(make_client, sessions):
    make_user(sessions, "seller@example.test")
    client = make_client()
    sign_in(client, "seller@example.test")
    token = client.cookies[COOKIE_NAME]
    assert client.post("/api/auth/logout").status_code == 204
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 0
    client.cookies.set(COOKIE_NAME, token)  # a replayed cookie is worthless
    assert client.get("/api/auth/me").status_code == 401


def test_me_requires_a_valid_session(make_client):
    client = make_client()
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.set(COOKIE_NAME, "forged")
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize(
    "origin", [None, "https://evil.example", "http://127.0.0.1:5173.evil.example", "null"]
)
def test_mutations_from_other_or_missing_origins_are_refused(make_client, sessions, origin):
    make_user(sessions, "seller@example.test")
    response = make_client(origin=origin).post(
        "/api/auth/login", json={"email": "seller@example.test", "password": PASSWORD}
    )
    assert response.status_code == 403
    assert "set-cookie" not in response.headers


def test_origin_check_covers_uploads_and_logout(make_client, sessions):
    make_user(sessions, "seller@example.test")
    client = make_client()
    sign_in(client, "seller@example.test")
    evil = {"Origin": "https://evil.example"}
    assert client.post("/api/auth/logout", headers=evil).status_code == 403
    assert (
        client.post("/api/seller/datasets", headers=evil, files={"file": ("a.csv", b"a\n1\n")}).status_code
        == 403
    )
    assert client.get("/api/auth/me").status_code == 200  # still signed in


def test_allowed_origins_are_configurable(settings, engine, store, sessions):
    from fastapi.testclient import TestClient

    from sliver_api.main import create_app

    make_user(sessions, "seller@example.test")
    custom = settings.model_copy(update={"sliver_allowed_origins": "https://sliver.example/"})
    with TestClient(create_app(custom, engine=engine, store=store)) as client:
        body = {"email": "seller@example.test", "password": PASSWORD}
        assert client.post(
            "/api/auth/login", json=body, headers={"Origin": "https://sliver.example"}
        ).is_success
        local = {"Origin": "http://127.0.0.1:5173"}
        assert client.post("/api/auth/login", json=body, headers=local).status_code == 403


def test_seed_gives_demo_accounts_passwords_from_the_environment(sessions, store, make_client):
    seed(sessions, store, FIXTURES, ("seller-pass", "reviewer-pass"))
    with sessions() as db:
        seller = db.scalar(select(User).where(User.role == "seller"))
        reviewer = db.scalar(select(User).where(User.email == REVIEWER_EMAIL))
    assert reviewer.role == "reviewer"
    client = make_client()
    sign_in(client, seller.email, "seller-pass")
    sign_in(make_client(), REVIEWER_EMAIL, "reviewer-pass")

    # Re-seeding with empty passwords fails closed: hashes and live sessions are removed.
    seed(sessions, store, FIXTURES, ("", ""))
    with sessions() as db:
        assert db.scalars(select(User.password_hash)).all() == [None, None]
    assert client.get("/api/auth/me").status_code == 401
    response = make_client().post("/api/auth/login", json={"email": seller.email, "password": "seller-pass"})
    assert response.status_code == 401


def test_reseeding_with_the_same_password_keeps_sessions(sessions, store, make_client):
    seed(sessions, store, FIXTURES, ("seller-pass", ""))
    with sessions() as db:
        email = db.scalar(select(User.email).where(User.role == "seller"))
    client = make_client()
    sign_in(client, email, "seller-pass")
    seed(sessions, store, FIXTURES, ("seller-pass", ""))
    assert client.get("/api/auth/me").status_code == 200
