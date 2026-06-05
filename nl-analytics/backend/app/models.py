from pydantic import BaseModel, Field
from typing import Any


class SessionCreate(BaseModel):
    name: str = Field(default="New session", max_length=120)


class SessionOut(BaseModel):
    id: str
    name: str
    created_at: str
    updated_at: str
    file_count: int = 0
    message_count: int = 0


class TableInfo(BaseModel):
    name: str
    original_filename: str
    row_count: int
    col_count: int
    columns: list[dict[str, Any]]   # [{name, type, sample}]
    sample_rows: list[dict[str, Any]]


class Relationship(BaseModel):
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    confidence: float


class SchemaOut(BaseModel):
    tables: list[TableInfo]
    relationships: list[Relationship]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class MessageOut(BaseModel):
    id: int
    role: str
    question: str | None = None
    sql: str | None = None
    text: str | None = None
    chart_spec: dict | None = None
    result_preview: dict | None = None
    row_count: int | None = None
    error: str | None = None
    created_at: str


class UploadResult(BaseModel):
    uploaded: list[dict[str, Any]]
    skipped: list[dict[str, Any]]
