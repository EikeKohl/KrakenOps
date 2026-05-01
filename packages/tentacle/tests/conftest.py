"""Pytest fixtures for tentacle tests.

OpenTelemetry only allows `set_tracer_provider()` once per process, so the
TracerProvider + InMemorySpanExporter pair is wired up once at session scope
and `.clear()`'d between tests.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tentacle import _core


@pytest.fixture(scope="session")
def _exporter() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "tentacle-test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter


@pytest.fixture
def spans(_exporter: InMemorySpanExporter) -> Iterator[InMemorySpanExporter]:
    """Per-test exporter view: cleared before/after each test."""
    _exporter.clear()
    # Pretend init() already ran so the public API behaves as if configured.
    _core._initialized = True
    try:
        yield _exporter
    finally:
        _exporter.clear()
        _core._reset_for_tests()
