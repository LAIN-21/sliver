"""The signed-in user, resolved from the session cookie on every request."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from ..deps import DB
from ..models import User
from .service import COOKIE_NAME, session_user


def current_user(request: Request, db: DB) -> User:
    user = session_user(db, request.cookies.get(COOKIE_NAME))
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return user


def current_seller(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "seller":
        raise HTTPException(status_code=403, detail="Only sellers can do this.")
    return user


def current_reviewer(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "reviewer":
        raise HTTPException(status_code=403, detail="Only reviewers can do this.")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
CurrentSeller = Annotated[User, Depends(current_seller)]
CurrentReviewer = Annotated[User, Depends(current_reviewer)]
