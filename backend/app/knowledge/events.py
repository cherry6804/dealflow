"""Outbox event names for knowledge ingestion (DFR1-016). Kept separate so the document service can enqueue without importing the handler."""

INGEST_REQUESTED_EVENT = "knowledge.ingest_requested"
