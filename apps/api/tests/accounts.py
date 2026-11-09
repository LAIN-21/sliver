"""Helpers for tests that need signed-in sellers and reviewers."""

from sliver_api.auth.passwords import hash_password
from sliver_api.models import User

PASSWORD = "correct horse battery staple"


def make_user(sessions, email: str, role: str = "seller", password: str | None = PASSWORD) -> User:
    with sessions() as db:
        user = User(
            email=email,
            display_name=email.split("@")[0],
            role=role,
            password_hash=hash_password(password) if password else None,
        )
        db.add(user)
        db.commit()
        return user


def sign_in(client, email: str, password: str = PASSWORD):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response
