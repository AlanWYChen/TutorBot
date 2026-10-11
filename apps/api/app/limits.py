"""Shared binary limits for contracts, storage and HTTP ingestion."""

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_DOCUMENT_PAGES = 200
MAX_MULTIPART_BYTES = MAX_UPLOAD_BYTES + 64 * 1024
