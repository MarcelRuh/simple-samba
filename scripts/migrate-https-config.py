#!/usr/bin/env python3
"""Stellt HTTPS als Standard ein und migriert bestehende HTTP-only-Konfigurationen."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.https_migrate import migrate  # noqa: E402

if __name__ == "__main__":
    if migrate():
        print("HTTPS-Konfiguration aktualisiert.")
    else:
        print("HTTPS-Konfiguration bereits aktuell.")
