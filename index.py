"""Vercel entrypoint: serves the FastAPI backend and the built React frontend.

Vercel's filesystem is read-only except /tmp, so data lives there (it resets on cold starts).
"""
import os
import sys

os.environ.setdefault("SGCL_DATA_DIR", "/tmp/sgcl")
os.environ.setdefault("SGCL_SYNC_PROCESSING", "1")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from app.main import app  # noqa: E402,F401
