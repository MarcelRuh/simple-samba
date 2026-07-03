"""CSRF-Schutz für Formulare und API-Aufrufe."""

from __future__ import annotations

import secrets
from functools import wraps
from typing import Any, Callable

from flask import abort, request, session

CSRF_SESSION_KEY = "_csrf_token"


def get_csrf_token() -> str:
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_hex(32)
        session[CSRF_SESSION_KEY] = token
    return token


def validate_csrf_token() -> None:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    expected = session.get(CSRF_SESSION_KEY)
    token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    if not expected or not token or token != expected:
        abort(403)


def csrf_protect(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        validate_csrf_token()
        return view(*args, **kwargs)

    return wrapped
