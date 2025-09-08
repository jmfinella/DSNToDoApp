from dataclasses import dataclass
from typing import Optional
from dataclasses import dataclass
from typing import Optional


@dataclass
class Context:
    id: str
    name: str
    color: Optional[str] = None


@dataclass
class Task:
    id: str
    title: str
    status: str
    context: str  # context id
    owner: str    # user id
    kind: str = "todo"  # todo | event | routine
    priority: int = 0
    position: float = 1.0
    journal_date: Optional[str] = None  # YYYY-MM-DD
    due_date: Optional[str] = None
    notes: Optional[str] = None
    parent_task: Optional[str] = None