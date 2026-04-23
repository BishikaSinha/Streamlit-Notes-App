"""SQLite database layer for Smart Notepad Pro."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from utils import now_str, safe_json_dumps


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "smart_notepad_pro.db"
BACKUP_DIR = BASE_DIR / "backups"

DEFAULT_SETTINGS = {
    "theme": "dark",
    "default_sort": "last_updated",
    "autosave": "1",
    "writing_goal": "500",
    "focus_mode": "0",
}


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def query_one(sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    with get_connection() as conn:
        cur = conn.execute(sql, tuple(params))
        return _row_to_dict(cur.fetchone())


def query_all(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    with get_connection() as conn:
        cur = conn.execute(sql, tuple(params))
        return [_row_to_dict(row) for row in cur.fetchall() if row is not None]


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with get_connection() as conn:
        cur = conn.execute(sql, tuple(params))
        return cur.lastrowid


def init_db(seed_demo: bool = True) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            );

            CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL COLLATE NOCASE,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, name),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL COLLATE NOCASE,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, name),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                folder_id INTEGER,
                title TEXT NOT NULL,
                content TEXT,
                note_type TEXT NOT NULL DEFAULT 'markdown',
                pinned INTEGER NOT NULL DEFAULT 0,
                favorite INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                trashed INTEGER NOT NULL DEFAULT 0,
                color_label TEXT DEFAULT 'Slate',
                locked INTEGER NOT NULL DEFAULT 0,
                use_encryption INTEGER NOT NULL DEFAULT 0,
                lock_password_hash TEXT,
                lock_password_salt TEXT,
                encryption_salt TEXT,
                encrypted_content TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_opened_at TEXT,
                open_count INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(folder_id) REFERENCES folders(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS note_tags (
                note_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                PRIMARY KEY(note_id, tag_id),
                FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE,
                FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS note_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_id INTEGER NOT NULL,
                version_number INTEGER NOT NULL,
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS activity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                note_id INTEGER,
                action TEXT NOT NULL,
                details_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                UNIQUE(user_id, key),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )

    if seed_demo and count_users() == 0:
        seed_demo_data()


def count_users() -> int:
    row = query_one("SELECT COUNT(*) AS count FROM users")
    return int(row["count"]) if row else 0


def get_user_by_identifier(identifier: str) -> dict[str, Any] | None:
    if not identifier:
        return None
    return query_one(
        """
        SELECT * FROM users
        WHERE lower(username) = lower(?) OR lower(email) = lower(?)
        LIMIT 1
        """,
        (identifier, identifier),
    )


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    return query_one("SELECT * FROM users WHERE id = ?", (user_id,))


def create_user_record(username: str, email: str, password_hash: str) -> int:
    return execute(
        """
        INSERT INTO users (username, email, password_hash, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (username, email or None, password_hash, now_str()),
    )


def update_last_login(user_id: int) -> None:
    execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_str(), user_id))


def ensure_folder(user_id: int, name: str) -> int:
    clean = name.strip()
    existing = query_one(
        "SELECT id FROM folders WHERE user_id = ? AND lower(name) = lower(?)",
        (user_id, clean),
    )
    if existing:
        return int(existing["id"])
    return execute(
        """
        INSERT INTO folders (user_id, name, created_at)
        VALUES (?, ?, ?)
        """,
        (user_id, clean, now_str()),
    )


def ensure_tag(user_id: int, name: str) -> int:
    clean = name.strip()
    existing = query_one(
        "SELECT id FROM tags WHERE user_id = ? AND lower(name) = lower(?)",
        (user_id, clean),
    )
    if existing:
        return int(existing["id"])
    return execute(
        """
        INSERT INTO tags (user_id, name, created_at)
        VALUES (?, ?, ?)
        """,
        (user_id, clean, now_str()),
    )


def list_folders(user_id: int) -> list[dict[str, Any]]:
    return query_all(
        "SELECT * FROM folders WHERE user_id = ? ORDER BY name COLLATE NOCASE",
        (user_id,),
    )


def list_tags(user_id: int) -> list[dict[str, Any]]:
    return query_all(
        "SELECT * FROM tags WHERE user_id = ? ORDER BY name COLLATE NOCASE",
        (user_id,),
    )


def get_folder_by_name(user_id: int, name: str) -> dict[str, Any] | None:
    return query_one(
        "SELECT * FROM folders WHERE user_id = ? AND lower(name) = lower(?) LIMIT 1",
        (user_id, name.strip()),
    )


def get_tag_by_name(user_id: int, name: str) -> dict[str, Any] | None:
    return query_one(
        "SELECT * FROM tags WHERE user_id = ? AND lower(name) = lower(?) LIMIT 1",
        (user_id, name.strip()),
    )


def set_setting(user_id: int, key: str, value: Any) -> None:
    execute(
        """
        INSERT INTO settings (user_id, key, value)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value
        """,
        (user_id, key, "" if value is None else str(value)),
    )


def get_setting(user_id: int, key: str, default: Any = None) -> Any:
    row = query_one(
        "SELECT value FROM settings WHERE user_id = ? AND key = ?",
        (user_id, key),
    )
    if row is None:
        return default
    return row["value"]


def get_settings(user_id: int) -> dict[str, Any]:
    settings = DEFAULT_SETTINGS.copy()
    rows = query_all("SELECT key, value FROM settings WHERE user_id = ?", (user_id,))
    for row in rows:
        settings[row["key"]] = row["value"]
    return settings


def ensure_default_settings(user_id: int) -> None:
    for key, value in DEFAULT_SETTINGS.items():
        if get_setting(user_id, key, None) is None:
            set_setting(user_id, key, value)


def backup_database() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    destination = BACKUP_DIR / f"smart_notepad_pro_{now_str().replace(':', '-').replace(' ', '_')}.db"
    if DB_PATH.exists():
        shutil.copy2(DB_PATH, destination)
    return destination


def restore_database(source_file: str | os.PathLike[str]) -> Path:
    source = Path(source_file)
    if not source.exists():
        raise FileNotFoundError(str(source))
    shutil.copy2(source, DB_PATH)
    return DB_PATH


def seed_demo_data() -> None:
    from auth import hash_password

    demo_password = "demo12345"
    demo_user_id = create_user_record("demo", "demo@smartnotepad.pro", hash_password(demo_password))
    ensure_default_settings(demo_user_id)
    personal_folder = ensure_folder(demo_user_id, "Personal")
    work_folder = ensure_folder(demo_user_id, "Work")
    ideas_folder = ensure_folder(demo_user_id, "Ideas")
    tag_welcome = ensure_tag(demo_user_id, "Welcome")
    tag_productivity = ensure_tag(demo_user_id, "Productivity")
    tag_checklist = ensure_tag(demo_user_id, "Checklist")
    tag_plans = ensure_tag(demo_user_id, "Plans")
    created = now_str()
    notes = [
        (
            demo_user_id,
            personal_folder,
            "Welcome to Smart Notepad Pro",
            "This is your polished, Python-only Streamlit notepad.\n\n- Use the editor to create notes\n- Organize with folders and tags\n- Try the dashboard for charts and streaks",
            "markdown",
            1,
            1,
            0,
            0,
            "Ocean",
            0,
            0,
            None,
            None,
            None,
            None,
            created,
            created,
            created,
            3,
        ),
        (
            demo_user_id,
            work_folder,
            "Project Launch Checklist",
            "- [ ] Finalize product scope\n- [x] Build core app\n- [ ] Add screenshots\n- [ ] Share with teammates",
            "checklist",
            1,
            0,
            0,
            0,
            "Emerald",
            0,
            0,
            None,
            None,
            None,
            None,
            created,
            created,
            created,
            1,
        ),
        (
            demo_user_id,
            ideas_folder,
            "Private Brainstorm",
            "A locked note demo. This note illustrates note protection.\n\nYou can turn on encryption from the editor once unlocked.",
            "markdown",
            0,
            1,
            0,
            0,
            "Violet",
            0,
            0,
            None,
            None,
            None,
            None,
            created,
            created,
            created,
            2,
        ),
    ]
    for note in notes:
        note_id = execute(
            """
            INSERT INTO notes (
                user_id, folder_id, title, content, note_type,
                pinned, favorite, archived, trashed, color_label,
                locked, use_encryption, lock_password_hash, lock_password_salt,
                encryption_salt, encrypted_content, created_at, updated_at,
                last_opened_at, open_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            note,
        )
        if note[2] == "Welcome to Smart Notepad Pro":
            note_tags = [tag_welcome, tag_productivity]
        elif note[2] == "Project Launch Checklist":
            note_tags = [tag_checklist, tag_plans]
        else:
            note_tags = [tag_welcome]
        for tag_id in note_tags:
            execute(
                "INSERT OR IGNORE INTO note_tags (note_id, tag_id) VALUES (?, ?)",
                (note_id, tag_id),
            )
        log_activity(
            demo_user_id,
            "seed_note",
            note_id=note_id,
            details={"title": note[2], "tags": note_tags},
        )


def log_activity(user_id: int, action: str, note_id: int | None = None, details: dict[str, Any] | None = None) -> int:
    return execute(
        """
        INSERT INTO activity_logs (user_id, note_id, action, details_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, note_id, action, safe_json_dumps(details or {}), now_str()),
    )

