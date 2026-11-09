from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..config import Settings
from ..deps import DB
from ..models import User
from .deps import CurrentUser
from .passwords import MAX_PASSWORD_CHARS
from .service import COOKIE_NAME, authenticate, end_session, start_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_CHARS)


def account(user: User) -> dict:
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role}


@router.post("/login")
def login(body: Login, request: Request, response: Response, db: DB) -> dict:
    settings: Settings = request.app.state.settings
    user = authenticate(db, body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    token = start_session(db, user, settings.session_ttl_hours)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_ttl_hours * 3600,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
    )
    return {"user": account(user)}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: DB) -> None:
    end_session(db, request.cookies.get(COOKIE_NAME))
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")


@router.get("/me")
def me(user: CurrentUser) -> dict:
    return {"user": account(user)}
