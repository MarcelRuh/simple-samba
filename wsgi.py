"""WSGI-Einstiegspunkt für Gunicorn."""

from app.app import app

__all__ = ["app"]
