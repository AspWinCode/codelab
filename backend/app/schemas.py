from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class ProblemTestIn(BaseModel):
    input: str
    expected: str
    is_hidden: bool = False
    group: str = "default"
    weight: float = 1.0


class ProblemRevisionCreate(BaseModel):
    title: str
    statement: str = ""
    input_format: Optional[str] = None
    output_format: Optional[str] = None
    constraints: Optional[str] = None
    examples: List[dict] = []
    template_code: Optional[str] = None
    reference_solution: Optional[str] = None
    language: str = "python3"
    time_limit_ms: int = 2000
    memory_limit_mb: int = 256
    allowed_libraries: List[str] = []
    tests: List[ProblemTestIn] = []
    checker: str = "exact"
    max_attempts: Optional[int] = None
    scoring_policy: str = "best"


class ProblemRevisionOut(ProblemRevisionCreate):
    id: int
    task_id: int
    revision_number: int

    model_config = ConfigDict(from_attributes=True)


class CourseCreate(BaseModel):
    title: str
    slug: Optional[str] = None
    description: Optional[str] = None


class CourseOut(BaseModel):
    id: int
    slug: Optional[str]
    title: str
    description: Optional[str]
    status: str

    model_config = ConfigDict(from_attributes=True)


class SubmissionCreate(BaseModel):
    problem_revision_id: int
    code: str
    language: str = "python3"


class SubmissionOut(BaseModel):
    id: int
    status: str
    verdict: Optional[str]
    score: Optional[float]
    stdout: Optional[str]
    stderr: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RunRequest(BaseModel):
    """IDE-003: запуск на пользовательском вводе без создания оцениваемой посылки."""

    problem_revision_id: int
    code: str
    stdin: str = ""


class RunResult(BaseModel):
    stdout: str
    stderr: str
    timed_out: bool


class MeOut(BaseModel):
    id: int
    external_ref: str
    full_name: str
    role: str
    groups: List[str]
    directions: List[str]

    model_config = ConfigDict(from_attributes=True)
