"""Request-scoped dependencies."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.sessions() as session:
        yield session


DB = Annotated[Session, Depends(get_db)]
