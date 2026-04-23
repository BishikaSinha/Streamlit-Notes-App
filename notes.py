"""Business logic for notes, versions, search, import, export, and encryption."""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from cryptography.fernet import Fernet, InvalidToken

import auth
import db
from utils import (
    as_list,
    checklist_lines,
    color_hex,
    count_chars,
    count_words,
    format_dt,
    now_str,
    normalize_title,
    reading_time_minutes,
    safe_json_dumps,
    safe_json_loads,
    snippet,
    split_tags,
    strip_markdown,
    unique_non_empty,
)


NOTE_SORTS = {
    "Newest": "created_at DESC",
    "Oldest": "created_at ASC",
    "Alphabetical": "title COLLATE NOCASE ASC",
    "Last Updated": "updated_at DESC",
}


def derive_fernet_key(password: str, salt_b64: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt = base64.b64decode(salt_b64)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390_000)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def encrypt_text(text: str, password: str, salt_b64: str | None = None) -> tuple[str, str]:
    salt = salt_b64 or base64.b64encode(os.urandom(16)).decode("ascii")
    key = derive_fernet_key(password, salt)
    encrypted = Fernet(key).encrypt(text.encode("utf-8")).decode("ascii")
    return encrypted, salt


def decrypt_text(encrypted_text: str, password: str, salt_b64: str) -> str:
    key = derive_fernet_key(password, salt_b64)
    return Fernet(key).decrypt(encrypted_text.encode("ascii")).decode("utf-8")


def _note_tags(note_id: int) -> list[str]:
    rows = db.query_all(
        """
        SELECT t.name
        FROM note_tags nt
        JOIN tags t ON t.id = nt.tag_id
        WHERE nt.note_id = ?
        ORDER BY t.name COLLATE NOCASE
        """,
        (note_id,),
    )
    return [row["name"] for row in rows]


def get_note(user_id: int, note_id: int) -> dict[str, Any] | None:
    note = db.query_one(
        """
        SELECT n.*, f.name AS folder_name
        FROM notes n
        LEFT JOIN folders f ON f.id = n.folder_id
        WHERE n.user_id = ? AND n.id = ?
        LIMIT 1
        """,
        (user_id, note_id),
    )
    if not note:
        return None
    note["tags"] = _note_tags(note_id)
    return note


def note_snapshot(user_id: int, note_id: int) -> dict[str, Any] | None:
    note = get_note(user_id, note_id)
    if not note:
        return None
    return {
        "note": note,
        "tags": note.get("tags", []),
    }


def _version_number(note_id: int) -> int:
    row = db.query_one(
        "SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version FROM note_versions WHERE note_id = ?",
        (note_id,),
    )
    return int(row["next_version"]) if row else 1


def _save_version(note_id: int, snapshot: dict[str, Any]) -> None:
    db.execute(
        """
        INSERT INTO note_versions (note_id, version_number, snapshot_json, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (note_id, _version_number(note_id), safe_json_dumps(snapshot), now_str()),
    )


def _note_payload(note: dict[str, Any], tags: Iterable[str] | None = None) -> dict[str, Any]:
    return {
        "id": note["id"],
        "title": note["title"],
        "content": note.get("content"),
        "note_type": note.get("note_type", "markdown"),
        "folder_id": note.get("folder_id"),
        "folder_name": note.get("folder_name"),
        "pinned": int(note.get("pinned", 0)),
        "favorite": int(note.get("favorite", 0)),
        "archived": int(note.get("archived", 0)),
        "trashed": int(note.get("trashed", 0)),
        "color_label": note.get("color_label") or "Slate",
        "locked": int(note.get("locked", 0)),
        "use_encryption": int(note.get("use_encryption", 0)),
        "lock_password_hash": note.get("lock_password_hash"),
        "lock_password_salt": note.get("lock_password_salt"),
        "encryption_salt": note.get("encryption_salt"),
        "encrypted_content": note.get("encrypted_content"),
        "tags": list(tags or note.get("tags", [])),
        "created_at": note.get("created_at"),
        "updated_at": note.get("updated_at"),
        "last_opened_at": note.get("last_opened_at"),
        "open_count": int(note.get("open_count", 0)),
    }


def _apply_note_tags(note_id: int, user_id: int, tags: Iterable[str]) -> None:
    db.execute("DELETE FROM note_tags WHERE note_id = ?", (note_id,))
    for tag in unique_non_empty(tags):
        tag_id = db.ensure_tag(user_id, tag)
        db.execute(
            "INSERT OR IGNORE INTO note_tags (note_id, tag_id) VALUES (?, ?)",
            (note_id, tag_id),
        )


def _encrypt_if_needed(content: str, locked: bool, use_encryption: bool, password: str | None, existing_note: dict[str, Any] | None = None) -> tuple[str | None, str | None, str | None, str | None]:
    if not locked:
        return content, None, None, None
    password = password or None
    if use_encryption:
        if not password:
            if existing_note and existing_note.get("lock_password_salt"):
                raise ValueError("Password is required to encrypt the note.")
            raise ValueError("Password is required to encrypt the note.")
        encrypted, enc_salt = encrypt_text(content or "", password)
        return None, encrypted, enc_salt, auth.hash_password(password)
    if not password:
        if existing_note and existing_note.get("lock_password_hash"):
            return content, existing_note.get("encrypted_content"), existing_note.get("encryption_salt"), existing_note.get("lock_password_hash")
        raise ValueError("Password is required to lock the note.")
    return content, None, None, auth.hash_password(password)


def create_note(
    user_id: int,
    title: str,
    content: str,
    folder_name: str | None = None,
    tags: Iterable[str] | None = None,
    note_type: str = "markdown",
    pinned: bool = False,
    favorite: bool = False,
    archived: bool = False,
    trashed: bool = False,
    color_label: str = "Slate",
    locked: bool = False,
    use_encryption: bool = False,
    lock_password: str | None = None,
) -> int:
    clean_title = normalize_title(title)
    folder_id = db.ensure_folder(user_id, folder_name) if folder_name else None
    payload_content, encrypted_content, encryption_salt, lock_password_hash = _encrypt_if_needed(
        content,
        locked,
        use_encryption,
        lock_password,
    )
    note_id = db.execute(
        """
        INSERT INTO notes (
            user_id, folder_id, title, content, note_type,
            pinned, favorite, archived, trashed, color_label,
            locked, use_encryption, lock_password_hash, lock_password_salt,
            encryption_salt, encrypted_content, created_at, updated_at,
            last_opened_at, open_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            folder_id,
            clean_title,
            payload_content,
            note_type,
            int(pinned),
            int(favorite),
            int(archived),
            int(trashed),
            color_label,
            int(locked),
            int(use_encryption),
            lock_password_hash,
            None if not locked else (lock_password_hash.split("$", 3)[2] if lock_password_hash else None),
            encryption_salt,
            encrypted_content,
            now_str(),
            now_str(),
            None,
            0,
        ),
    )
    _apply_note_tags(note_id, user_id, tags or [])
    db.log_activity(
        user_id,
        "create_note",
        note_id=note_id,
        details={
            "title": clean_title,
            "words": count_words(content),
            "chars": count_chars(content),
            "note_type": note_type,
        },
    )
    return note_id


def _get_password_salt_from_hash(password_hash: str | None) -> str | None:
    if not password_hash:
        return None
    try:
        return password_hash.split("$", 3)[2]
    except Exception:
        return None


def update_note(
    user_id: int,
    note_id: int,
    title: str,
    content: str,
    folder_name: str | None = None,
    tags: Iterable[str] | None = None,
    note_type: str = "markdown",
    pinned: bool = False,
    favorite: bool = False,
    archived: bool = False,
    trashed: bool = False,
    color_label: str = "Slate",
    locked: bool = False,
    use_encryption: bool = False,
    lock_password: str | None = None,
) -> bool:
    existing = get_note(user_id, note_id)
    if not existing:
        return False
    _save_version(note_id, _note_payload(existing, existing.get("tags", [])))
    folder_id = db.ensure_folder(user_id, folder_name) if folder_name else None
    payload_content, encrypted_content, encryption_salt, lock_password_hash = _encrypt_if_needed(
        content,
        locked,
        use_encryption,
        lock_password,
        existing_note=existing,
    )
    if locked and not use_encryption and not lock_password_hash:
        lock_password_hash = existing.get("lock_password_hash")
    lock_password_salt = _get_password_salt_from_hash(lock_password_hash) if lock_password_hash else None
    db.execute(
        """
        UPDATE notes SET
            folder_id = ?,
            title = ?,
            content = ?,
            note_type = ?,
            pinned = ?,
            favorite = ?,
            archived = ?,
            trashed = ?,
            color_label = ?,
            locked = ?,
            use_encryption = ?,
            lock_password_hash = ?,
            lock_password_salt = ?,
            encryption_salt = ?,
            encrypted_content = ?,
            updated_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (
            folder_id,
            normalize_title(title),
            payload_content,
            note_type,
            int(pinned),
            int(favorite),
            int(archived),
            int(trashed),
            color_label,
            int(locked),
            int(use_encryption),
            lock_password_hash,
            lock_password_salt,
            encryption_salt,
            encrypted_content,
            now_str(),
            note_id,
            user_id,
        ),
    )
    _apply_note_tags(note_id, user_id, tags or [])
    db.log_activity(
        user_id,
        "update_note",
        note_id=note_id,
        details={
            "title": normalize_title(title),
            "words": count_words(content),
            "chars": count_chars(content),
            "note_type": note_type,
        },
    )
    return True


def save_editor_note(user_id: int, note_id: int | None, payload: dict[str, Any]) -> tuple[bool, str, int | None]:
    try:
        if note_id:
            ok = update_note(user_id, note_id, **payload)
            return ok, "Note updated.", note_id if ok else None
        new_id = create_note(user_id, **payload)
        return True, "Note created.", new_id
    except Exception as exc:
        return False, str(exc), note_id


def delete_to_trash(user_id: int, note_ids: Iterable[int]) -> None:
    ids = [int(i) for i in note_ids]
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    db.execute(
        f"UPDATE notes SET trashed = 1, archived = 0, updated_at = ? WHERE user_id = ? AND id IN ({placeholders})",
        (now_str(), user_id, *ids),
    )
    for note_id in ids:
        db.log_activity(user_id, "trash_note", note_id=note_id)


def restore_from_trash(user_id: int, note_ids: Iterable[int]) -> None:
    ids = [int(i) for i in note_ids]
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    db.execute(
        f"UPDATE notes SET trashed = 0, updated_at = ? WHERE user_id = ? AND id IN ({placeholders})",
        (now_str(), user_id, *ids),
    )
    for note_id in ids:
        db.log_activity(user_id, "restore_note", note_id=note_id)


def permanent_delete(user_id: int, note_ids: Iterable[int]) -> None:
    ids = [int(i) for i in note_ids]
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    for note_id in ids:
        db.log_activity(user_id, "delete_note", note_id=note_id)
    db.execute(
        f"DELETE FROM note_tags WHERE note_id IN (SELECT id FROM notes WHERE user_id = ? AND id IN ({placeholders}))",
        (user_id, *ids),
    )
    db.execute(
        f"DELETE FROM note_versions WHERE note_id IN (SELECT id FROM notes WHERE user_id = ? AND id IN ({placeholders}))",
        (user_id, *ids),
    )
    db.execute(
        f"DELETE FROM notes WHERE user_id = ? AND id IN ({placeholders})",
        (user_id, *ids),
    )


def duplicate_note(user_id: int, note_id: int) -> int | None:
    note = get_note(user_id, note_id)
    if not note:
        return None
    return create_note(
        user_id=user_id,
        title=f"{note['title']} Copy",
        content=note.get("content") or "",
        folder_name=note.get("folder_name"),
        tags=note.get("tags", []),
        note_type=note.get("note_type", "markdown"),
        pinned=False,
        favorite=False,
        archived=False,
        trashed=False,
        color_label=note.get("color_label") or "Slate",
        locked=False,
        use_encryption=False,
    )


def mark_favorite(user_id: int, note_ids: Iterable[int], favorite: bool) -> None:
    ids = [int(i) for i in note_ids]
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    db.execute(
        f"UPDATE notes SET favorite = ?, updated_at = ? WHERE user_id = ? AND id IN ({placeholders})",
        (int(favorite), now_str(), user_id, *ids),
    )


def pin_notes(user_id: int, note_ids: Iterable[int], pinned: bool) -> None:
    ids = [int(i) for i in note_ids]
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    db.execute(
        f"UPDATE notes SET pinned = ?, updated_at = ? WHERE user_id = ? AND id IN ({placeholders})",
        (int(pinned), now_str(), user_id, *ids),
    )


def archive_notes(user_id: int, note_ids: Iterable[int], archived: bool) -> None:
    ids = [int(i) for i in note_ids]
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    db.execute(
        f"UPDATE notes SET archived = ?, trashed = 0, updated_at = ? WHERE user_id = ? AND id IN ({placeholders})",
        (int(archived), now_str(), user_id, *ids),
    )


def get_versions(note_id: int) -> list[dict[str, Any]]:
    return db.query_all(
        """
        SELECT * FROM note_versions
        WHERE note_id = ?
        ORDER BY version_number DESC, created_at DESC
        """,
        (note_id,),
    )


def restore_version(user_id: int, note_id: int, version_id: int) -> bool:
    note = get_note(user_id, note_id)
    version = db.query_one(
        "SELECT * FROM note_versions WHERE id = ? AND note_id = ?",
        (version_id, note_id),
    )
    if not note or not version:
        return False
    snapshot = safe_json_loads(version["snapshot_json"], {})
    if "note" not in snapshot:
        return False
    current_payload = _note_payload(note, note.get("tags", []))
    _save_version(note_id, current_payload)
    restored = snapshot["note"]
    _apply_note_tags(note_id, user_id, restored.get("tags", []))
    db.execute(
        """
        UPDATE notes SET
            folder_id = ?,
            title = ?,
            content = ?,
            note_type = ?,
            pinned = ?,
            favorite = ?,
            archived = ?,
            trashed = ?,
            color_label = ?,
            locked = ?,
            use_encryption = ?,
            lock_password_hash = ?,
            lock_password_salt = ?,
            encryption_salt = ?,
            encrypted_content = ?,
            updated_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (
            restored.get("folder_id"),
            restored.get("title"),
            restored.get("content"),
            restored.get("note_type", "markdown"),
            int(restored.get("pinned", 0)),
            int(restored.get("favorite", 0)),
            int(restored.get("archived", 0)),
            int(restored.get("trashed", 0)),
            restored.get("color_label", "Slate"),
            int(restored.get("locked", 0)),
            int(restored.get("use_encryption", 0)),
            restored.get("lock_password_hash"),
            restored.get("lock_password_salt"),
            restored.get("encryption_salt"),
            restored.get("encrypted_content"),
            now_str(),
            note_id,
            user_id,
        ),
    )
    db.log_activity(user_id, "restore_version", note_id=note_id, details={"version_id": version_id})
    return True


def set_note_lock(
    user_id: int,
    note_id: int,
    password: str,
    use_encryption: bool = False,
) -> bool:
    note = get_note(user_id, note_id)
    if not note:
        return False
    content = note.get("content") or ""
    payload_content, encrypted_content, encryption_salt, lock_password_hash = _encrypt_if_needed(
        content,
        True,
        use_encryption,
        password,
        existing_note=note,
    )
    db.execute(
        """
        UPDATE notes SET
            locked = 1,
            use_encryption = ?,
            lock_password_hash = ?,
            lock_password_salt = ?,
            encryption_salt = ?,
            encrypted_content = ?,
            content = ?,
            updated_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (
            int(use_encryption),
            lock_password_hash,
            _get_password_salt_from_hash(lock_password_hash),
            encryption_salt,
            encrypted_content,
            payload_content,
            now_str(),
            note_id,
            user_id,
        ),
    )
    db.log_activity(user_id, "lock_note", note_id=note_id, details={"encrypted": bool(use_encryption)})
    return True


def remove_note_lock(user_id: int, note_id: int, content: str | None = None) -> bool:
    note = get_note(user_id, note_id)
    if not note:
        return False
    content = content if content is not None else note.get("content")
    if note.get("locked") and note.get("use_encryption") and not content:
        raise ValueError("Unlock the note before removing encryption.")
    db.execute(
        """
        UPDATE notes SET
            locked = 0,
            use_encryption = 0,
            content = ?,
            lock_password_hash = NULL,
            lock_password_salt = NULL,
            encryption_salt = NULL,
            encrypted_content = NULL,
            updated_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (content, now_str(), note_id, user_id),
    )
    db.log_activity(user_id, "unlock_note", note_id=note_id)
    return True


def verify_note_password(note: dict[str, Any], password: str) -> bool:
    stored = note.get("lock_password_hash")
    if not stored:
        return False
    return auth.verify_password(password, stored)


def note_content_for_display(note: dict[str, Any], password: str | None = None) -> str:
    if not note:
        return ""
    if not int(note.get("locked", 0)):
        return note.get("content") or ""
    if not password:
        raise ValueError("Password required to open this note.")
    if not verify_note_password(note, password):
        raise ValueError("Incorrect password.")
    if not int(note.get("use_encryption", 0)):
        return note.get("content") or ""
    encrypted = note.get("encrypted_content") or ""
    if not encrypted:
        return note.get("content") or ""
    return decrypt_text(encrypted, password, note["encryption_salt"])


def unlock_note(user_id: int, note_id: int, password: str) -> tuple[bool, str, str | None]:
    note = get_note(user_id, note_id)
    if not note:
        return False, "Note not found.", None
    if not verify_note_password(note, password):
        return False, "Incorrect password.", None
    content = note_content_for_display(note, password=password)
    db.execute(
        "UPDATE notes SET open_count = open_count + 1, last_opened_at = ?, updated_at = ? WHERE id = ? AND user_id = ?",
        (now_str(), now_str(), note_id, user_id),
    )
    db.log_activity(user_id, "open_note", note_id=note_id)
    return True, "Note unlocked.", content


def mark_opened(user_id: int, note_id: int) -> None:
    db.execute(
        "UPDATE notes SET open_count = open_count + 1, last_opened_at = ? WHERE id = ? AND user_id = ?",
        (now_str(), note_id, user_id),
    )
    db.log_activity(user_id, "open_note", note_id=note_id)


def fetch_notes_overview(user_id: int, include_trashed: bool = True) -> pd.DataFrame:
    rows = db.query_all(
        """
        SELECT
            n.*,
            f.name AS folder_name,
            COALESCE(GROUP_CONCAT(t.name, '||'), '') AS tags_csv
        FROM notes n
        LEFT JOIN folders f ON f.id = n.folder_id
        LEFT JOIN note_tags nt ON nt.note_id = n.id
        LEFT JOIN tags t ON t.id = nt.tag_id
        WHERE n.user_id = ?
        GROUP BY n.id
        ORDER BY n.updated_at DESC, n.id DESC
        """,
        (user_id,),
    )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["tags_list"] = df["tags_csv"].fillna("").apply(lambda value: [tag for tag in value.split("||") if tag])
    if not include_trashed:
        df = df[df["trashed"] == 0]
    return df.reset_index(drop=True)


def filter_notes(
    user_id: int,
    search: str = "",
    folder: str | None = None,
    tags: Iterable[str] | None = None,
    pinned: bool | None = None,
    favorite: bool | None = None,
    archived: bool | None = None,
    trashed: bool | None = None,
    sort_label: str = "Last Updated",
) -> pd.DataFrame:
    df = fetch_notes_overview(user_id, include_trashed=True)
    if df.empty:
        return df
    if search:
        query = search.lower().strip()
        mask = df["title"].str.lower().str.contains(query, na=False) | df["content"].fillna("").str.lower().str.contains(query, na=False)
        df = df[mask]
    if folder and folder != "All":
        df = df[df["folder_name"].fillna("") == folder]
    if tags:
        wanted = {tag.lower() for tag in tags if tag}
        df = df[df["tags_list"].apply(lambda values: bool(wanted.intersection({v.lower() for v in values})))] if wanted else df
    if pinned is not None:
        df = df[df["pinned"] == int(pinned)]
    if favorite is not None:
        df = df[df["favorite"] == int(favorite)]
    if archived is not None:
        df = df[df["archived"] == int(archived)]
    if trashed is not None:
        df = df[df["trashed"] == int(trashed)]

    if sort_label == "Newest":
        df = df.sort_values("created_at", ascending=False)
    elif sort_label == "Oldest":
        df = df.sort_values("created_at", ascending=True)
    elif sort_label == "Alphabetical":
        df = df.sort_values("title", ascending=True, key=lambda s: s.str.lower())
    else:
        df = df.sort_values("updated_at", ascending=False)
    return df.reset_index(drop=True)


def stats_for_user(user_id: int) -> dict[str, Any]:
    notes_df = fetch_notes_overview(user_id)
    if notes_df.empty:
        return {
            "total_notes": 0,
            "favorites": 0,
            "pinned": 0,
            "archived": 0,
            "trash": 0,
            "total_words": 0,
            "recent_notes": [],
            "folder_counts": [],
            "tag_counts": [],
            "activity_df": pd.DataFrame(),
            "recent_activity": [],
            "recently_opened": [],
            "streak": 0,
            "today_words": 0,
        }
    active = notes_df[notes_df["trashed"] == 0]
    recent_notes = active.sort_values("updated_at", ascending=False).head(6).to_dict("records")
    recently_opened = active.sort_values("last_opened_at", ascending=False, na_position="last").head(6).to_dict("records")
    total_words = int(active["content"].fillna("").apply(count_words).sum())
    folder_counts = active["folder_name"].fillna("No folder").value_counts().reset_index()
    folder_counts.columns = ["folder", "count"]
    tag_series = active["tags_list"].explode()
    tag_counts = tag_series[tag_series.notna() & (tag_series != "")].value_counts().reset_index()
    tag_counts.columns = ["tag", "count"]
    activities = db.query_all(
        """
        SELECT * FROM activity_logs
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 120
        """,
        (user_id,),
    )
    activity_df = pd.DataFrame(activities)
    if not activity_df.empty:
        activity_df["details"] = activity_df["details_json"].apply(lambda v: safe_json_loads(v, {}))
        activity_df["date"] = pd.to_datetime(activity_df["created_at"]).dt.date
    words_by_day = pd.DataFrame()
    if not activity_df.empty:
        create_mask = activity_df["action"].isin(["create_note", "update_note", "seed_note"])
        words_by_day = activity_df[create_mask].copy()
        if not words_by_day.empty:
            words_by_day["words"] = words_by_day["details"].apply(lambda d: int(d.get("words", 0)))
            words_by_day = words_by_day.groupby("date")["words"].sum().reset_index()
    recent_activity = activities[:12]
    streak = calculate_streak(activity_df)
    today_words = 0
    if not activity_df.empty:
        today = pd.Timestamp.now().date()
        today_rows = activity_df[activity_df["date"] == today]
        if not today_rows.empty:
            today_words = int(today_rows["details"].apply(lambda d: int(d.get("words", 0))).sum())
    return {
        "total_notes": int(len(active)),
        "favorites": int(active["favorite"].sum()),
        "pinned": int(active["pinned"].sum()),
        "archived": int(active["archived"].sum()),
        "trash": int(notes_df["trashed"].sum()),
        "total_words": total_words,
        "recent_notes": recent_notes,
        "recently_opened": recently_opened,
        "folder_counts": folder_counts,
        "tag_counts": tag_counts,
        "activity_df": activity_df,
        "word_activity": words_by_day,
        "recent_activity": recent_activity,
        "streak": streak,
        "today_words": today_words,
    }


def calculate_streak(activity_df: pd.DataFrame) -> int:
    if activity_df.empty:
        return 0
    relevant = activity_df[activity_df["action"].isin(["create_note", "update_note", "seed_note"])]
    if relevant.empty:
        return 0
    dates = sorted(set(relevant["date"]))
    if not dates:
        return 0
    streak = 0
    current = pd.Timestamp.now().date()
    while current in dates:
        streak += 1
        current = current - pd.Timedelta(days=1)
    return streak


def render_content_preview(note: dict[str, Any]) -> str:
    if int(note.get("locked", 0)):
        return "[Locked note]"
    content = note.get("content") or ""
    if note.get("note_type") == "checklist":
        items = checklist_lines(content)
        preview = " | ".join(("x" if done else " ") + " " + item for done, item in items[:4])
        return preview or "[Checklist note]"
    return snippet(strip_markdown(content), 160)


def export_note_text(note: dict[str, Any], password: str | None = None) -> str:
    if int(note.get("locked", 0)) and password:
        body = note_content_for_display(note, password=password)
    elif int(note.get("locked", 0)):
        body = "[Locked note content not exported without unlocking]"
    else:
        body = note.get("content") or ""
    lines = [
        f"Title: {note['title']}",
        f"Folder: {note.get('folder_name') or ''}",
        f"Tags: {', '.join(note.get('tags', []))}",
        f"Created: {format_dt(note.get('created_at'))}",
        f"Updated: {format_dt(note.get('updated_at'))}",
        "",
        body,
    ]
    return "\n".join(lines).strip() + "\n"


def export_note_markdown(note: dict[str, Any], password: str | None = None) -> str:
    if int(note.get("locked", 0)) and password:
        body = note_content_for_display(note, password=password)
    elif int(note.get("locked", 0)):
        body = "_Locked note content not exported without unlocking_"
    else:
        body = note.get("content") or ""
    return f"# {note['title']}\n\n{body}\n"


def export_all_notes_json(user_id: int) -> str:
    notes_df = fetch_notes_overview(user_id)
    folders = db.list_folders(user_id)
    tags = db.list_tags(user_id)
    notes_json = [] if notes_df.empty else json.loads(notes_df.to_json(orient="records"))
    for record in notes_json:
        record["tags"] = list(record.get("tags_list", []))
    payload = {
        "exported_at": now_str(),
        "folders": folders,
        "tags": tags,
        "notes": notes_json,
    }
    return safe_json_dumps(payload)


def import_txt_note(user_id: int, title: str, content: str, folder_name: str | None = None, tags: Iterable[str] | None = None) -> int:
    return create_note(user_id, title=title, content=content, folder_name=folder_name, tags=tags, note_type="markdown")


def import_md_note(user_id: int, title: str, markdown_text: str, folder_name: str | None = None, tags: Iterable[str] | None = None) -> int:
    return create_note(user_id, title=title, content=markdown_text, folder_name=folder_name, tags=tags, note_type="markdown")


def import_json_backup(user_id: int, raw_json: str) -> tuple[int, int]:
    payload = safe_json_loads(raw_json, {})
    imported_folders = 0
    imported_notes = 0
    folder_lookup: dict[str, int] = {}
    for folder in payload.get("folders", []):
        name = folder.get("name")
        if name:
            folder_lookup[name] = db.ensure_folder(user_id, name)
            imported_folders += 1
    for tag in payload.get("tags", []):
        name = tag.get("name")
        if name:
            db.ensure_tag(user_id, name)
    for note in payload.get("notes", []):
        folder_name = note.get("folder_name")
        tags = note.get("tags", [])
        create_note(
            user_id=user_id,
            title=note.get("title", "Imported Note"),
            content=note.get("content", "") or "",
            folder_name=folder_name,
            tags=tags,
            note_type=note.get("note_type", "markdown"),
            pinned=bool(note.get("pinned", 0)),
            favorite=bool(note.get("favorite", 0)),
            archived=bool(note.get("archived", 0)),
            trashed=bool(note.get("trashed", 0)),
            color_label=note.get("color_label", "Slate"),
            locked=bool(note.get("locked", 0)),
            use_encryption=bool(note.get("use_encryption", 0)),
        )
        imported_notes += 1
    return imported_folders, imported_notes


def export_note_blob(note: dict[str, Any], kind: str = "txt") -> tuple[str, bytes]:
    if kind == "txt":
        data = export_note_text(note).encode("utf-8")
        filename = f"{re.sub(r'[^A-Za-z0-9_-]+', '_', note['title']).strip('_') or 'note'}.txt"
    elif kind == "md":
        data = export_note_markdown(note).encode("utf-8")
        filename = f"{re.sub(r'[^A-Za-z0-9_-]+', '_', note['title']).strip('_') or 'note'}.md"
    else:
        data = safe_json_dumps(note).encode("utf-8")
        filename = "note.json"
    return filename, data


def note_display_payload(user_id: int, note_id: int, password: str | None = None) -> dict[str, Any] | None:
    note = get_note(user_id, note_id)
    if not note:
        return None
    content = note.get("content") or ""
    if int(note.get("locked", 0)) and int(note.get("use_encryption", 0)):
        if password:
            content = note_content_for_display(note, password=password)
        else:
            content = ""
    return {
        **note,
        "content": content,
        "word_count": count_words(content),
        "char_count": count_chars(content),
        "reading_time": reading_time_minutes(content),
        "content_preview": render_content_preview({**note, "content": content}),
    }
