"""SQLModel models — pure Python views over the SQL in migrations/001_initial.sql.

Keeping these as plain SQLModel `table=False` (i.e. NOT auto-creating tables)
because schema is owned by SQL migrations. Models are used for SELECT/INSERT
ergonomics only.
"""

from __future__ import annotations

from sqlmodel import Field, SQLModel


class Trace(SQLModel, table=True):
    __tablename__ = "traces"
    trace_id: str = Field(primary_key=True)
    service_name: str
    started_at_ns: int
    ended_at_ns: int | None = None
    span_count: int = 0
    has_human_review: int = 0


class Span(SQLModel, table=True):
    __tablename__ = "spans"
    span_id: str = Field(primary_key=True)
    trace_id: str = Field(index=True, foreign_key="traces.trace_id")
    parent_span_id: str | None = None
    name: str
    otel_kind: str
    tentacle_kind: str | None = None
    start_time_ns: int
    end_time_ns: int
    status_code: str
    status_message: str | None = None
    attributes_json: str
    events_json: str
    needs_human_review: int = 0


class TokenUsage(SQLModel, table=True):
    __tablename__ = "token_usage"
    span_id: str = Field(primary_key=True, foreign_key="spans.span_id")
    trace_id: str = Field(index=True, foreign_key="traces.trace_id")
    gen_ai_system: str | None = None
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None = None


class ModelPricing(SQLModel, table=True):
    __tablename__ = "model_pricing"
    model: str = Field(primary_key=True)
    input_per_1k_usd: float
    output_per_1k_usd: float
    source: str
    updated_at_s: int
