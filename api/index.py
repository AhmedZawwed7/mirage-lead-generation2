"""Vercel serverless entrypoint for the Mirage Flask application."""
import os

# The deployed function filesystem is read-only except for /tmp.
# SQLite here is temporary; production persistence must use a managed database.
os.environ.setdefault("MIRAGE_DB", "/tmp/mirage-leads-hunter.db")

from app import app  # noqa: E402
