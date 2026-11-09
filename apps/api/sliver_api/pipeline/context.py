from dataclasses import dataclass
from functools import cached_property

from sqlalchemy.orm import Session

from ..models import Dataset
from ..storage import ObjectStore
from .table import Table, read_table


@dataclass
class StageContext:
    db: Session
    store: ObjectStore
    dataset: Dataset
    data: bytes

    @cached_property
    def table(self) -> Table:
        return read_table(self.data)
