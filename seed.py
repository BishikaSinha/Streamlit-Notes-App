"""Seed helper for Smart Notepad Pro."""

from __future__ import annotations

import db


if __name__ == "__main__":
    db.init_db(seed_demo=True)
    print(f"Database initialized at: {db.DB_PATH}")

