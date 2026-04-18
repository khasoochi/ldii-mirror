"""Vercel serverless entry point.

Vercel's @vercel/python runtime imports a WSGI `app` object from this module.
The Flask app itself lives in the repo root, so we prepend the parent directory
to sys.path and re-export it.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app  # noqa: E402,F401
