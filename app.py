"""Smart Notepad Pro - Streamlit application."""

from __future__ import annotations

import base64
import json
import re
import time
from io import BytesIO
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

import auth
import db
import notes
from styles import get_css
from utils import (
    COLOR_LABELS,
    as_list,
    checklist_lines,
    color_hex,
    count_chars,
    count_words,
    format_bytes,
    format_dt,
    html_escape,
    normalize_title,
    reading_time_minutes,
    snippet,
    split_tags,
    strip_markdown,
    unique_non_empty,
    writing_goal_progress,
)


st.set_page_config(
    page_title="Smart Notepad Pro",
    page_icon="SN",
    layout="wide",
    initial_sidebar_state="expanded",
)


def rerun() -> None:
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


def init_session() -> None:
    defaults = {
        "authenticated": False,
        "user": None,
        "page": "Dashboard",
        "selected_note_id": None,
        "selected_note_ids": [],
        "note_unlock_cache": {},
        "editor_initialized_for": None,
        "editor_title": "",
        "editor_content": "",
        "editor_folder": "No folder",
        "editor_tags": [],
        "editor_note_type": "markdown",
        "editor_pinned": False,
        "editor_favorite": False,
        "editor_archived": False,
        "editor_trashed": False,
        "editor_color": "Slate",
        "editor_locked": False,
        "editor_use_encryption": False,
        "editor_lock_password": "",
        "editor_lock_password_confirm": "",
        "editor_focus_mode": False,
        "editor_preview_mode": True,
        "quick_note_title": "",
        "quick_note_content": "",
        "quick_note_folder": "No folder",
        "quick_note_tags": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def load_user_settings() -> dict[str, str]:
    user = st.session_state.get("user")
    if not user:
        return db.DEFAULT_SETTINGS.copy()
    settings = db.get_settings(user["id"])
    st.session_state["theme"] = settings.get("theme", "dark")
    st.session_state["default_sort"] = settings.get("default_sort", "last_updated")
    st.session_state["autosave"] = settings.get("autosave", "1") == "1"
    st.session_state["writing_goal"] = int(settings.get("writing_goal", "500") or 500)
    st.session_state["focus_mode_default"] = settings.get("focus_mode", "0") == "1"
    st.session_state["editor_focus_mode"] = st.session_state["focus_mode_default"]
    return settings


def apply_styles() -> None:
    theme = st.session_state.get("theme", "dark")
    st.markdown(get_css(theme), unsafe_allow_html=True)


def html_chip(text: str, bg: str) -> str:
    return f'<span class="sn-chip" style="background:{bg};">{html_escape(text)}</span>'


def note_color_chip(label: str) -> str:
    return html_chip(label, color_hex(label))


def markdown_card(title: str, body: str, footer: str = "") -> None:
    st.markdown(
        f"""
        <div class="sn-card">
            <div class="sn-note-title">{html_escape(title)}</div>
            <div class="sn-muted" style="white-space: pre-wrap;">{html_escape(body)}</div>
            {f'<div class="sn-muted" style="margin-top:0.6rem;">{html_escape(footer)}</div>' if footer else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def hero(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="sn-hero">
            <h1 style="margin:0 0 0.3rem 0;">{html_escape(title)}</h1>
            <p style="margin:0;color:var(--sn-muted);font-size:1rem;">{html_escape(subtitle)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def login_page() -> None:
    hero("Smart Notepad Pro", "A polished, Python-only Streamlit notebook for serious writing, organization, and productivity.")
    left, right = st.columns([1.05, 0.95], gap="large")
    with left:
        st.markdown("### Login")
        with st.form("login_form", clear_on_submit=False):
            identifier = st.text_input("Username or email")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Sign in")
        if submit:
            ok, message, user = auth.authenticate(identifier, password)
            if ok and user:
                st.session_state.authenticated = True
                st.session_state.user = user
                st.session_state.page = "Dashboard"
                load_user_settings()
                st.success(message)
                rerun()
            else:
                st.error(message)
    with right:
        st.markdown("### Create account")
        with st.form("signup_form", clear_on_submit=False):
            username = st.text_input("Username")
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            confirm = st.text_input("Confirm password", type="password")
            submit = st.form_submit_button("Create account")
        if submit:
            if password != confirm:
                st.error("Passwords do not match.")
            else:
                ok, message, user = auth.create_user(username, email, password)
                if ok and user:
                    st.session_state.authenticated = True
                    st.session_state.user = user
                    st.session_state.page = "Dashboard"
                    load_user_settings()
                    st.success(message)
                    rerun()
                else:
                    st.error(message)
        st.markdown(
            """
            <div class="sn-inline-panel">
            <strong>Demo account</strong><br>
            Username: <code>demo</code><br>
            Password: <code>demo12345</code>
            </div>
            """,
            unsafe_allow_html=True,
        )


def sidebar_navigation() -> None:
    user = st.session_state.user
    with st.sidebar:
        st.markdown("## Smart Notepad Pro")
        st.caption(f"Signed in as {user['username']}")
        page = st.radio(
            "Navigation",
            [
                "Dashboard",
                "All Notes",
                "Editor",
                "Favorites",
                "Archived",
                "Trash",
                "Settings",
            ],
            index=[
                "Dashboard",
                "All Notes",
                "Editor",
                "Favorites",
                "Archived",
                "Trash",
                "Settings",
            ].index(st.session_state.page),
        )
        st.session_state.page = page
        st.divider()
        st.markdown("### Quick Note")
        with st.form("quick_note_form", clear_on_submit=False):
            q_title = st.text_input("Title", value=st.session_state.quick_note_title)
            q_content = st.text_area("Content", value=st.session_state.quick_note_content, height=140)
            folders = [row["name"] for row in db.list_folders(user["id"])]
            folder_options = ["No folder"] + folders
            q_folder = st.selectbox("Folder", folder_options, index=folder_options.index(st.session_state.quick_note_folder) if st.session_state.quick_note_folder in folder_options else 0)
            q_tags = st.text_input("Tags", value=st.session_state.quick_note_tags, placeholder="ideas, work, urgent")
            submit = st.form_submit_button("Create quick note")
        st.session_state.quick_note_title = q_title
        st.session_state.quick_note_content = q_content
        st.session_state.quick_note_folder = q_folder
        st.session_state.quick_note_tags = q_tags
        if submit:
            note_id = notes.create_note(
                user_id=user["id"],
                title=q_title,
                content=q_content,
                folder_name=None if q_folder == "No folder" else q_folder,
                tags=split_tags(q_tags),
            )
            st.session_state.selected_note_id = note_id
            st.session_state.page = "Editor"
            st.success("Quick note created.")
            rerun()
        st.divider()
        if st.button("Logout"):
            st.session_state.authenticated = False
            st.session_state.user = None
            st.session_state.selected_note_id = None
            st.session_state.selected_note_ids = []
            st.session_state.note_unlock_cache = {}
            st.session_state.page = "Dashboard"
            rerun()


def current_user_id() -> int:
    return int(st.session_state.user["id"])


def unlocked_cache(note_id: int) -> str | None:
    return st.session_state.note_unlock_cache.get(str(note_id))


def set_unlocked_cache(note_id: int, password: str) -> None:
    st.session_state.note_unlock_cache[str(note_id)] = password


def clear_unlocked_cache(note_id: int) -> None:
    st.session_state.note_unlock_cache.pop(str(note_id), None)


def note_content_for_editor(note: dict[str, object]) -> str:
    if int(note.get("locked", 0)) and int(note.get("use_encryption", 0)):
        password = unlocked_cache(note["id"])
        if password:
            return notes.note_content_for_display(note, password=password)
        return ""
    return note.get("content") or ""


def create_duplicate_from_payload(
    title: str,
    content: str,
    folder_name: str | None,
    tags: list[str],
    note_type: str,
    color_label: str,
) -> int:
    return notes.create_note(
        current_user_id(),
        title=title,
        content=content,
        folder_name=folder_name,
        tags=tags,
        note_type=note_type,
        pinned=False,
        favorite=False,
        archived=False,
        trashed=False,
        color_label=color_label,
        locked=False,
        use_encryption=False,
    )


def note_card(note: dict[str, object], show_actions: bool = True) -> None:
    locked = int(note.get("locked", 0))
    trashed = int(note.get("trashed", 0))
    note_id = int(note["id"])
    display_content = note.get("content") or ""
    if locked and unlocked_cache(note_id):
        try:
            display_content = notes.note_content_for_display(note, password=unlocked_cache(note_id))
        except Exception:
            display_content = note.get("content") or ""
    preview = notes.render_content_preview(note)
    if locked and unlocked_cache(note_id):
        preview = snippet(strip_markdown(display_content), 160) or preview
    tags = note.get("tags_list", [])
    badges = []
    if note.get("pinned"):
        badges.append(html_chip("Pinned", "rgba(56,189,248,0.8)"))
    if note.get("favorite"):
        badges.append(html_chip("Favorite", "rgba(245,158,11,0.8)"))
    if note.get("archived"):
        badges.append(html_chip("Archived", "rgba(100,116,139,0.85)"))
    if trashed:
        badges.append(html_chip("Trash", "rgba(244,63,94,0.8)"))
    if locked:
        badges.append(html_chip("Locked", "rgba(139,92,246,0.82)"))
    badges.append(note_color_chip(note.get("color_label") or "Slate"))
    footer = f"Updated {format_dt(note.get('updated_at'))} | {count_words(display_content)} words | {reading_time_minutes(display_content)} min read"
    st.markdown(
        f"""
        <div class="sn-card">
            <div class="sn-note-title">{html_escape(note['title'])}</div>
            <div class="sn-note-meta">{html_escape(note.get('folder_name') or 'No folder')}</div>
            <div class="sn-badges">{''.join(badges)}</div>
            <div class="sn-muted" style="margin-top:0.5rem; white-space: pre-wrap;">{html_escape(preview)}</div>
            <div class="sn-muted" style="margin-top:0.65rem; font-size:0.82rem;">{html_escape(footer)}</div>
            <div class="sn-muted" style="margin-top:0.5rem; font-size:0.82rem;">Tags: {html_escape(', '.join(tags) if tags else 'None')}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if show_actions:
        cols = st.columns(5)
        with cols[0]:
            if st.button("Open", key=f"open_{note['id']}"):
                st.session_state.selected_note_id = note_id
                st.session_state.page = "Editor"
                rerun()
        with cols[1]:
            if st.button("Duplicate", key=f"dup_{note['id']}"):
                if locked and not unlocked_cache(note_id):
                    st.error("Unlock the note first to duplicate it.")
                else:
                    content = note.get("content") or ""
                    if locked:
                        try:
                            content = notes.note_content_for_display(note, password=unlocked_cache(note_id))
                        except Exception as exc:
                            st.error(str(exc))
                            return
                    new_id = create_duplicate_from_payload(
                        title=f"{note['title']} Copy",
                        content=content,
                        folder_name=note.get("folder_name"),
                        tags=list(note.get("tags", [])),
                        note_type=note.get("note_type", "markdown"),
                        color_label=note.get("color_label") or "Slate",
                    )
                    st.success("Note duplicated.")
                    st.session_state.selected_note_id = new_id
                    st.session_state.page = "Editor"
                    rerun()
        with cols[2]:
            if trashed:
                if st.button("Restore", key=f"restore_{note['id']}"):
                    notes.restore_from_trash(current_user_id(), [int(note["id"])])
                    st.success("Restored from trash.")
                    rerun()
            else:
                if st.button("Trash", key=f"trash_{note['id']}"):
                    notes.delete_to_trash(current_user_id(), [int(note["id"])])
                    st.warning("Moved to trash.")
                    rerun()
        with cols[3]:
            if st.button("Fav", key=f"fav_{note['id']}"):
                notes.mark_favorite(current_user_id(), [int(note["id"])], not bool(note.get("favorite")))
                rerun()
        with cols[4]:
            if st.button("Pin", key=f"pin_{note['id']}"):
                notes.pin_notes(current_user_id(), [int(note["id"])], not bool(note.get("pinned")))
                rerun()


def note_list_page(df: pd.DataFrame, title: str, subtitle: str, trash_mode: bool = False) -> None:
    hero(title, subtitle)
    if df.empty:
        st.markdown(
            """
            <div class="sn-empty">
                Nothing here yet. Create a note from the editor or the quick note box in the sidebar.
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    select_all = st.checkbox("Enable bulk selection", value=False, key=f"bulk_enable_{title}")
    selected = []
    if select_all:
        options = df["id"].tolist()
        default_selected = [nid for nid in st.session_state.selected_note_ids if nid in options]
        selected = st.multiselect("Select notes", options=options, default=default_selected, key=f"bulk_select_{title}")
        st.session_state.selected_note_ids = selected
        bulk_cols = st.columns(6 if trash_mode else 5)
        with bulk_cols[0]:
            if st.button("Pin selected"):
                notes.pin_notes(current_user_id(), selected, True)
                rerun()
        with bulk_cols[1]:
            if st.button("Favorite selected"):
                notes.mark_favorite(current_user_id(), selected, True)
                rerun()
        with bulk_cols[2]:
            if st.button("Archive selected"):
                notes.archive_notes(current_user_id(), selected, True)
                rerun()
        with bulk_cols[3]:
            if st.button("Trash selected") and not trash_mode:
                notes.delete_to_trash(current_user_id(), selected)
                rerun()
        with bulk_cols[4]:
            if st.button("Restore selected") and trash_mode:
                notes.restore_from_trash(current_user_id(), selected)
                rerun()
        if trash_mode:
            with bulk_cols[5]:
                if st.button("Delete selected"):
                    notes.permanent_delete(current_user_id(), selected)
                    rerun()
    for _, row in df.iterrows():
        note_card(row.to_dict())


def dashboard_page() -> None:
    stats = notes.stats_for_user(current_user_id())
    hero("Dashboard", "A live view of your notes, writing progress, and recent activity.")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total Notes", stats["total_notes"])
    m2.metric("Favorites", stats["favorites"])
    m3.metric("Pinned", stats["pinned"])
    m4.metric("Archived", stats["archived"])
    m5.metric("Trash", stats["trash"])
    m6, m7, m8 = st.columns(3)
    m6.metric("Total Words", stats["total_words"])
    m7.metric("Writing Streak", f"{stats['streak']} days")
    m8.metric("Words Today", stats["today_words"])
    goal = st.session_state.get("writing_goal", 500)
    st.progress(writing_goal_progress(stats["today_words"], goal))
    st.caption(f"Today's writing goal: {goal} words")

    left, right = st.columns([1.2, 0.8], gap="large")
    with left:
        st.markdown("### Recent notes")
        if stats["recent_notes"]:
            for row in stats["recent_notes"][:5]:
                note_card(row, show_actions=False)
        else:
            st.markdown('<div class="sn-empty">No notes yet.</div>', unsafe_allow_html=True)
    with right:
        st.markdown("### Recently opened")
        if stats["recently_opened"]:
            for row in stats["recently_opened"][:5]:
                title = row.get("title")
                st.markdown(f"- {html_escape(title)}", unsafe_allow_html=True)
        else:
            st.caption("No opened notes yet.")

    chart_left, chart_right = st.columns(2, gap="large")
    with chart_left:
        st.markdown("### Tag distribution")
        tag_df = stats["tag_counts"]
        if isinstance(tag_df, pd.DataFrame) and not tag_df.empty:
            fig = px.bar(tag_df.head(12), x="tag", y="count", color="count", color_continuous_scale="Blues")
            fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10), coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("Add tags to see distribution.")
    with chart_right:
        st.markdown("### Folder distribution")
        folder_df = stats["folder_counts"]
        if isinstance(folder_df, pd.DataFrame) and not folder_df.empty:
            fig = px.pie(folder_df, names="folder", values="count", hole=0.45)
            fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No folders yet.")

    st.markdown("### Writing activity")
    activity_df = stats["word_activity"]
    if isinstance(activity_df, pd.DataFrame) and not activity_df.empty:
        fig = px.line(activity_df, x="date", y="words", markers=True)
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("Write or edit notes to populate the activity chart.")

    st.markdown("### Recent activity log")
    if stats["recent_activity"]:
        activity_rows = pd.DataFrame(stats["recent_activity"])
        activity_rows["when"] = activity_rows["created_at"].apply(format_dt)
        st.dataframe(activity_rows[["when", "action", "note_id"]], use_container_width=True, hide_index=True)
    else:
        st.caption("No activity yet.")

    st.markdown("### AI-ready summary placeholder")
    st.info(
        "This area is reserved for future AI summarization, semantic search, and note insights. "
        "For now it shows the metadata needed to plug in an assistant later."
    )


def note_filters_ui(df: pd.DataFrame, mode: str = "all") -> pd.DataFrame:
    user = st.session_state.user
    folders = ["All"] + [row["name"] for row in db.list_folders(user["id"])]
    tags = [row["name"] for row in db.list_tags(user["id"])]
    cols = st.columns([1.5, 1, 1, 1, 1, 1])
    with cols[0]:
        search = st.text_input("Search", placeholder="Search titles or note content")
    with cols[1]:
        folder = st.selectbox("Folder", folders)
    with cols[2]:
        tag_sel = st.multiselect("Tags", tags)
    with cols[3]:
        pinned = st.selectbox("Pinned", ["Any", "Yes", "No"], index=0)
    with cols[4]:
        favorite = st.selectbox("Favorite", ["Any", "Yes", "No"], index=0)
    with cols[5]:
        sort_map = {
            "last_updated": "Last Updated",
            "newest": "Newest",
            "oldest": "Oldest",
            "alphabetical": "Alphabetical",
        }
        default_sort = sort_map.get(db.get_setting(user["id"], "default_sort", "last_updated"), "Last Updated")
        sort = st.selectbox("Sort", ["Newest", "Oldest", "Alphabetical", "Last Updated"], index=["Newest", "Oldest", "Alphabetical", "Last Updated"].index(default_sort))

    pinned_val = None if pinned == "Any" else pinned == "Yes"
    favorite_val = None if favorite == "Any" else favorite == "Yes"
    if mode == "trash":
        archived = None
        trashed = True
    elif mode == "archived":
        archived = True
        trashed = False
    elif mode == "favorites":
        archived = None
        trashed = False
        favorite_val = True
    else:
        archived = None
        trashed = False

    return notes.filter_notes(
        current_user_id(),
        search=search,
        folder=folder,
        tags=tag_sel,
        pinned=pinned_val,
        favorite=favorite_val,
        archived=archived,
        trashed=trashed,
        sort_label=sort,
    )


def all_notes_page(mode: str = "all") -> None:
    title_map = {
        "all": ("All Notes", "Browse, search, filter, and bulk-manage every note you own."),
        "favorites": ("Favorites", "Your starred notes at a glance."),
        "archived": ("Archived Notes", "Notes you kept but tucked away."),
        "trash": ("Trash", "Soft-deleted notes can be restored or permanently removed."),
    }
    title, subtitle = title_map[mode]
    df = note_filters_ui(notes.fetch_notes_overview(current_user_id()), mode=mode)
    if mode == "favorites":
        df = df[df["favorite"] == 1] if not df.empty else df
    elif mode == "archived":
        df = df[df["archived"] == 1] if not df.empty else df
    elif mode == "trash":
        df = df[df["trashed"] == 1] if not df.empty else df
    else:
        df = df[df["trashed"] == 0] if not df.empty else df
    note_list_page(df.reset_index(drop=True), title, subtitle, trash_mode=(mode == "trash"))


def load_note_into_editor(note_id: int | None) -> None:
    if not note_id:
        return
    note = notes.get_note(current_user_id(), note_id)
    if not note:
        return
    if int(note.get("locked", 0)) and not unlocked_cache(note_id):
        st.session_state.editor_initialized_for = note_id
        st.session_state.editor_title = note["title"]
        st.session_state.editor_content = ""
        st.session_state.editor_folder = note.get("folder_name") or "No folder"
        st.session_state.editor_tags = list(note.get("tags", []))
        st.session_state.editor_note_type = note.get("note_type", "markdown")
        st.session_state.editor_pinned = bool(note.get("pinned", 0))
        st.session_state.editor_favorite = bool(note.get("favorite", 0))
        st.session_state.editor_archived = bool(note.get("archived", 0))
        st.session_state.editor_trashed = bool(note.get("trashed", 0))
        st.session_state.editor_color = note.get("color_label") or "Slate"
        st.session_state.editor_locked = True
        st.session_state.editor_use_encryption = bool(note.get("use_encryption", 0))
        st.session_state.editor_lock_password = ""
        st.session_state.editor_lock_password_confirm = ""
        return
    content = notes.note_content_for_display(note, password=unlocked_cache(note_id))
    st.session_state.editor_initialized_for = note_id
    st.session_state.editor_title = note["title"]
    st.session_state.editor_content = content
    st.session_state.editor_folder = note.get("folder_name") or "No folder"
    st.session_state.editor_tags = list(note.get("tags", []))
    st.session_state.editor_note_type = note.get("note_type", "markdown")
    st.session_state.editor_pinned = bool(note.get("pinned", 0))
    st.session_state.editor_favorite = bool(note.get("favorite", 0))
    st.session_state.editor_archived = bool(note.get("archived", 0))
    st.session_state.editor_trashed = bool(note.get("trashed", 0))
    st.session_state.editor_color = note.get("color_label") or "Slate"
    st.session_state.editor_locked = bool(note.get("locked", 0))
    st.session_state.editor_use_encryption = bool(note.get("use_encryption", 0))


def save_editor_changes(note_id: int | None) -> tuple[bool, str, int | None]:
    folder = st.session_state.editor_folder
    folder_name = None if folder == "No folder" else folder
    password = st.session_state.editor_lock_password.strip() or unlocked_cache(note_id or -1)
    payload = {
        "title": st.session_state.editor_title,
        "content": st.session_state.editor_content,
        "folder_name": folder_name,
        "tags": st.session_state.editor_tags,
        "note_type": st.session_state.editor_note_type,
        "pinned": st.session_state.editor_pinned,
        "favorite": st.session_state.editor_favorite,
        "archived": st.session_state.editor_archived,
        "trashed": st.session_state.editor_trashed,
        "color_label": st.session_state.editor_color,
        "locked": st.session_state.editor_locked,
        "use_encryption": st.session_state.editor_use_encryption,
        "lock_password": password if st.session_state.editor_locked else None,
    }
    if note_id:
        ok = notes.update_note(current_user_id(), note_id, **payload)
        if ok:
            if st.session_state.editor_locked and password:
                set_unlocked_cache(note_id, password)
            elif note_id:
                clear_unlocked_cache(note_id)
        return ok, "Note saved." if ok else "Save failed.", note_id
    new_id = notes.create_note(current_user_id(), **payload)
    if st.session_state.editor_locked and password:
        set_unlocked_cache(new_id, password)
    return True, "Note created.", new_id


def editor_snapshot() -> str:
    return json.dumps(
        {
            "title": st.session_state.editor_title,
            "content": st.session_state.editor_content,
            "folder": st.session_state.editor_folder,
            "tags": st.session_state.editor_tags,
            "note_type": st.session_state.editor_note_type,
            "pinned": st.session_state.editor_pinned,
            "favorite": st.session_state.editor_favorite,
            "archived": st.session_state.editor_archived,
            "trashed": st.session_state.editor_trashed,
            "color": st.session_state.editor_color,
            "locked": st.session_state.editor_locked,
            "encrypted": st.session_state.editor_use_encryption,
        },
        sort_keys=True,
    )


def render_editor() -> None:
    hero("Editor", "Write, preview, lock, version, and organize your notes from one place.")
    user_id = current_user_id()
    notes_df = notes.fetch_notes_overview(user_id)
    note_options = []
    if not notes_df.empty:
        note_options = [(int(row["id"]), row["title"]) for _, row in notes_df.iterrows()]
    selector_cols = st.columns([1.2, 0.8, 0.8])
    with selector_cols[0]:
        option_map = {"New note": None}
        option_map.update({f"{title} (#{note_id})": note_id for note_id, title in note_options})
        option_labels = list(option_map.keys())
        selected_index = 0
        if st.session_state.selected_note_id in option_map.values():
            for idx, label in enumerate(option_labels):
                if option_map[label] == st.session_state.selected_note_id:
                    selected_index = idx
                    break
        selected_label = st.selectbox("Open note", option_labels, index=selected_index)
        chosen_note_id = option_map[selected_label]
        if chosen_note_id != st.session_state.selected_note_id:
            st.session_state.selected_note_id = chosen_note_id
            st.session_state.editor_initialized_for = None
            if chosen_note_id:
                load_note_into_editor(chosen_note_id)
            else:
                st.session_state.editor_title = ""
                st.session_state.editor_content = ""
                st.session_state.editor_folder = "No folder"
                st.session_state.editor_tags = []
                st.session_state.editor_note_type = "markdown"
                st.session_state.editor_pinned = False
                st.session_state.editor_favorite = False
                st.session_state.editor_archived = False
                st.session_state.editor_trashed = False
                st.session_state.editor_color = "Slate"
                st.session_state.editor_locked = False
                st.session_state.editor_use_encryption = False
                st.session_state.editor_lock_password = ""
                st.session_state.editor_lock_password_confirm = ""
    with selector_cols[1]:
        if st.button("New blank note"):
            st.session_state.selected_note_id = None
            st.session_state.editor_initialized_for = None
            st.session_state.editor_title = ""
            st.session_state.editor_content = ""
            st.session_state.editor_tags = []
            st.session_state.editor_folder = "No folder"
            st.session_state.editor_note_type = "markdown"
            st.session_state.editor_locked = False
            st.session_state.editor_use_encryption = False
            st.session_state.editor_lock_password = ""
            st.session_state.editor_lock_password_confirm = ""
            rerun()
    with selector_cols[2]:
        if st.session_state.selected_note_id and st.button("Duplicate current"):
            duplicate_id = create_duplicate_from_payload(
                title=f"{st.session_state.editor_title} Copy",
                content=st.session_state.editor_content,
                folder_name=None if st.session_state.editor_folder == "No folder" else st.session_state.editor_folder,
                tags=list(st.session_state.editor_tags),
                note_type=st.session_state.editor_note_type,
                color_label=st.session_state.editor_color,
            )
            st.session_state.selected_note_id = duplicate_id
            load_note_into_editor(duplicate_id)
            st.success("Duplicate created.")
            rerun()

    if st.session_state.selected_note_id and st.session_state.editor_initialized_for != st.session_state.selected_note_id:
        load_note_into_editor(int(st.session_state.selected_note_id))
    elif st.session_state.selected_note_id is None and not st.session_state.editor_title:
        st.session_state.editor_initialized_for = None

    note_id = st.session_state.selected_note_id
    note = notes.get_note(user_id, int(note_id)) if note_id else None
    if note and int(note.get("locked", 0)) and not unlocked_cache(int(note_id)):
        st.warning("This note is locked. Enter the password to unlock it for the current session.")
        with st.form("unlock_form"):
            unlock_pw = st.text_input("Password", type="password")
            submit = st.form_submit_button("Unlock note")
        if submit:
            ok, message, content = notes.unlock_note(user_id, int(note_id), unlock_pw)
            if ok:
                set_unlocked_cache(int(note_id), unlock_pw)
                load_note_into_editor(int(note_id))
                st.session_state.editor_content = content or ""
                st.success(message)
                rerun()
            else:
                st.error(message)
        return

    focus_active = st.session_state.get("editor_focus_mode", False)
    if focus_active:
        st.markdown('<div class="sn-focus-shell">', unsafe_allow_html=True)
    editor_left, editor_right = st.columns([1.35, 0.75], gap="large")
    with editor_left:
        st.text_input("Title", key="editor_title")
        content_label = "Checklist items" if st.session_state.editor_note_type == "checklist" else "Content"
        st.text_area(content_label, key="editor_content", height=380 if st.session_state.get("editor_focus_mode", False) else 420)
        preview_tabs = st.tabs(["Preview", "Source", "AI-ready context"])
        with preview_tabs[0]:
            if st.session_state.editor_note_type == "checklist":
                items = checklist_lines(st.session_state.editor_content)
                if items:
                    for done, item in items:
                        st.checkbox(item, value=done, disabled=True)
                else:
                    st.caption("Checklist preview will appear here.")
            else:
                st.markdown(st.session_state.editor_content or "_Nothing to preview yet._")
        with preview_tabs[1]:
            st.code(st.session_state.editor_content or "", language="markdown")
        with preview_tabs[2]:
            st.info(
                f"Title: {st.session_state.editor_title or 'Untitled Note'} | "
                f"Words: {count_words(st.session_state.editor_content)} | "
                f"Characters: {count_chars(st.session_state.editor_content)} | "
                f"Reading time: {reading_time_minutes(st.session_state.editor_content)} min"
            )
            st.caption("This panel is intentionally ready for future AI summarization and embeddings.")
    with editor_right:
        folders = ["No folder"] + [row["name"] for row in db.list_folders(user_id)]
        tags = [row["name"] for row in db.list_tags(user_id)]
        st.session_state.editor_folder = st.selectbox("Folder", folders, index=folders.index(st.session_state.editor_folder) if st.session_state.editor_folder in folders else 0)
        st.session_state.editor_tags = st.multiselect("Tags", options=tags, default=st.session_state.editor_tags)
        new_tags = st.text_input("Add tags", placeholder="Comma-separated tags")
        if new_tags:
            st.session_state.editor_tags = unique_non_empty(list(st.session_state.editor_tags) + split_tags(new_tags))
        type_choice = st.selectbox("Note type", ["markdown", "checklist"], index=["markdown", "checklist"].index(st.session_state.editor_note_type) if st.session_state.editor_note_type in ["markdown", "checklist"] else 0)
        st.session_state.editor_note_type = type_choice
        flags = st.columns(2)
        with flags[0]:
            st.session_state.editor_pinned = st.checkbox("Pinned", value=st.session_state.editor_pinned)
            st.session_state.editor_archived = st.checkbox("Archived", value=st.session_state.editor_archived)
            st.session_state.editor_locked = st.checkbox("Lock note", value=st.session_state.editor_locked)
        with flags[1]:
            st.session_state.editor_favorite = st.checkbox("Favorite", value=st.session_state.editor_favorite)
            st.session_state.editor_trashed = st.checkbox("Move to trash", value=st.session_state.editor_trashed)
            st.session_state.editor_use_encryption = st.checkbox("Encrypt locked note", value=st.session_state.editor_use_encryption)
        st.session_state.editor_color = st.selectbox("Color label", list(COLOR_LABELS.keys()), index=list(COLOR_LABELS.keys()).index(st.session_state.editor_color) if st.session_state.editor_color in COLOR_LABELS else 0)
        st.text_input("Lock password", type="password", key="editor_lock_password")
        st.text_input("Confirm lock password", type="password", key="editor_lock_password_confirm")
        stats_box = st.container()
        with stats_box:
            st.markdown(
                f"""
                <div class="sn-inline-panel">
                    <strong>Word count:</strong> {count_words(st.session_state.editor_content)}<br>
                    <strong>Character count:</strong> {count_chars(st.session_state.editor_content)}<br>
                    <strong>Reading time:</strong> {reading_time_minutes(st.session_state.editor_content)} minutes
                </div>
                """,
                unsafe_allow_html=True,
            )
        save_cols = st.columns(3)
        with save_cols[0]:
            if st.button("Save note"):
                effective_password = st.session_state.editor_lock_password.strip() or (unlocked_cache(int(note_id)) if note_id else "")
                if st.session_state.editor_locked:
                    if not effective_password:
                        st.error("Enter a lock password before saving a locked note.")
                        return
                    if st.session_state.editor_use_encryption and st.session_state.editor_lock_password and st.session_state.editor_lock_password != st.session_state.editor_lock_password_confirm:
                        st.error("Password and confirmation must match for encrypted notes.")
                        return
                ok, message, saved_id = save_editor_changes(note_id if note else None)
                if ok:
                    st.session_state.selected_note_id = saved_id
                    st.session_state.autosave_snapshot = editor_snapshot()
                    st.session_state.autosave_dirty_since = None
                    st.success(message)
                    if saved_id:
                        st.session_state.editor_initialized_for = saved_id
                        load_note_into_editor(saved_id)
                    rerun()
                else:
                    st.error(message)
        with save_cols[1]:
            if st.button("Delete to trash") and note_id:
                notes.delete_to_trash(user_id, [int(note_id)])
                st.warning("Note moved to trash.")
                rerun()
        with save_cols[2]:
            if st.button("Remove lock") and note_id:
                try:
                    notes.remove_note_lock(user_id, int(note_id), content=st.session_state.editor_content)
                    st.success("Lock removed.")
                    clear_unlocked_cache(int(note_id))
                    load_note_into_editor(int(note_id))
                    rerun()
                except Exception as exc:
                    st.error(str(exc))

        st.markdown("### Versions")
        if note_id:
            versions = notes.get_versions(int(note_id))
            if versions:
                for version in versions[:5]:
                    cols = st.columns([0.9, 0.7])
                    with cols[0]:
                        st.caption(f"Version {version['version_number']} · {format_dt(version['created_at'])}")
                    with cols[1]:
                        if st.button("Restore", key=f"restore_version_{version['id']}"):
                            if notes.restore_version(user_id, int(note_id), int(version["id"])):
                                st.success("Version restored.")
                                load_note_into_editor(int(note_id))
                                rerun()
            else:
                st.caption("No saved versions yet.")

        st.markdown("### Export / import")
        if note:
            export_note = notes.get_note(user_id, int(note_id))
            if export_note:
                export_password = unlocked_cache(int(note_id))
                safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", export_note["title"]).strip("_") or "note"
                if st.download_button("Export TXT", data=notes.export_note_text(export_note, password=export_password), file_name=f"{safe_name}.txt"):
                    pass
                if st.download_button("Export Markdown", data=notes.export_note_markdown(export_note, password=export_password), file_name=f"{safe_name}.md"):
                    pass
        uploaded_txt = st.file_uploader("Import TXT / Markdown / JSON backup", type=["txt", "md", "markdown", "json"], accept_multiple_files=False)
        if uploaded_txt is not None:
            text = uploaded_txt.read().decode("utf-8", errors="ignore")
            suffix = uploaded_txt.name.lower().split(".")[-1]
            if suffix in {"txt", "md", "markdown"}:
                title = normalize_title(Path(uploaded_txt.name).stem.replace("_", " "))
                notes.import_md_note(user_id, title=title, markdown_text=text, folder_name=None if st.session_state.editor_folder == "No folder" else st.session_state.editor_folder, tags=st.session_state.editor_tags)
                st.success("Imported file.")
                rerun()
            elif suffix == "json":
                folders, imported = notes.import_json_backup(user_id, text)
                st.success(f"Imported {imported} notes and {folders} folders.")
                rerun()

    if focus_active:
        st.markdown("</div>", unsafe_allow_html=True)

    if st.session_state.get("autosave", False) and note_id:
        snapshot = editor_snapshot()
        last_snapshot = st.session_state.get("autosave_snapshot")
        dirty_since = st.session_state.get("autosave_dirty_since")
        if snapshot != last_snapshot:
            if dirty_since is None:
                st.session_state.autosave_dirty_since = time.time()
            elif time.time() - dirty_since >= 2.5:
                effective_password = st.session_state.editor_lock_password.strip() or unlocked_cache(int(note_id))
                if st.session_state.editor_locked and not effective_password:
                    st.session_state.autosave_dirty_since = None
                elif st.session_state.editor_locked and st.session_state.editor_use_encryption and st.session_state.editor_lock_password and st.session_state.editor_lock_password != st.session_state.editor_lock_password_confirm:
                    st.session_state.autosave_dirty_since = None
                else:
                    ok, _, saved_id = save_editor_changes(note_id)
                    if ok:
                        st.session_state.autosave_snapshot = snapshot
                        st.session_state.autosave_dirty_since = None
                        if saved_id:
                            st.session_state.selected_note_id = saved_id
        else:
            st.session_state.autosave_dirty_since = None


def settings_page() -> None:
    hero("Settings", "Tune the app appearance, behavior, and backup options.")
    user_id = current_user_id()
    settings = db.get_settings(user_id)
    s1, s2 = st.columns(2)
    with s1:
        theme = st.radio("Theme", ["dark", "light"], index=0 if settings.get("theme", "dark") == "dark" else 1, horizontal=True)
        default_sort = st.selectbox("Default sort", ["last_updated", "newest", "oldest", "alphabetical"], index=["last_updated", "newest", "oldest", "alphabetical"].index(settings.get("default_sort", "last_updated")))
        autosave = st.checkbox("Autosave", value=settings.get("autosave", "1") == "1")
        focus_mode = st.checkbox("Default focus mode", value=settings.get("focus_mode", "0") == "1")
        writing_goal = st.number_input("Daily writing goal", min_value=50, max_value=10000, value=int(settings.get("writing_goal", "500")))
        if st.button("Save settings"):
            db.set_setting(user_id, "theme", theme)
            db.set_setting(user_id, "default_sort", default_sort)
            db.set_setting(user_id, "autosave", "1" if autosave else "0")
            db.set_setting(user_id, "focus_mode", "1" if focus_mode else "0")
            db.set_setting(user_id, "writing_goal", int(writing_goal))
            load_user_settings()
            st.success("Settings saved.")
            rerun()
    with s2:
        st.markdown("### Backup and restore")
        if st.button("Create database backup"):
            backup_path = db.backup_database()
            st.success(f"Backup created: {backup_path.name}")
        latest_backup = sorted(Path(db.BACKUP_DIR).glob("smart_notepad_pro_*.db"))
        if latest_backup:
            backup_path = latest_backup[-1]
            st.caption(f"Latest backup: {backup_path.name}")
            st.download_button("Download latest database backup", data=backup_path.read_bytes(), file_name=backup_path.name)
        upload = st.file_uploader("Restore database backup", type=["db", "sqlite", "sqlite3"], key="restore_db")
        if upload is not None:
            tmp_path = Path(db.BASE_DIR) / f"_restore_{upload.name}"
            tmp_path.write_bytes(upload.getvalue())
            try:
                db.restore_database(tmp_path)
                st.success("Database restored. Reloading app.")
                rerun()
            finally:
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)

        st.markdown("### Export all notes as JSON")
        json_blob = notes.export_all_notes_json(user_id)
        st.download_button("Download JSON backup", data=json_blob, file_name="smart_notepad_pro_notes.json")

    st.markdown("### Import options")
    imported_file = st.file_uploader("Import TXT / Markdown / JSON", type=["txt", "md", "markdown", "json"], key="settings_import")
    if imported_file is not None:
        suffix = imported_file.name.lower().split(".")[-1]
        text = imported_file.read().decode("utf-8", errors="ignore")
        if suffix in {"txt", "md", "markdown"}:
            notes.import_md_note(user_id, title=normalize_title(Path(imported_file.name).stem.replace("_", " ")), markdown_text=text)
            st.success("Imported note.")
            rerun()
        else:
            folders, imported = notes.import_json_backup(user_id, text)
            st.success(f"Imported {imported} notes and {folders} folders.")
            rerun()

    st.markdown("### Activity summary")
    stats = notes.stats_for_user(user_id)
    activity_df = stats["activity_df"]
    if isinstance(activity_df, pd.DataFrame) and not activity_df.empty:
        st.dataframe(activity_df[["created_at", "action", "note_id"]].head(25), use_container_width=True, hide_index=True)
    else:
        st.caption("No activity recorded yet.")


def render_main() -> None:
    db.init_db(seed_demo=True)
    init_session()
    if not st.session_state.authenticated or not st.session_state.user:
        login_page()
        return
    load_user_settings()
    apply_styles()
    sidebar_navigation()
    if st.session_state.page == "Dashboard":
        dashboard_page()
    elif st.session_state.page == "All Notes":
        all_notes_page("all")
    elif st.session_state.page == "Editor":
        render_editor()
    elif st.session_state.page == "Favorites":
        all_notes_page("favorites")
    elif st.session_state.page == "Archived":
        all_notes_page("archived")
    elif st.session_state.page == "Trash":
        all_notes_page("trash")
    elif st.session_state.page == "Settings":
        settings_page()


def main() -> None:
    init_session()
    db.init_db(seed_demo=True)
    if st.session_state.authenticated and st.session_state.user:
        apply_styles()
        sidebar_navigation()
        if st.session_state.page == "Dashboard":
            dashboard_page()
        elif st.session_state.page == "All Notes":
            all_notes_page("all")
        elif st.session_state.page == "Editor":
            render_editor()
        elif st.session_state.page == "Favorites":
            all_notes_page("favorites")
        elif st.session_state.page == "Archived":
            all_notes_page("archived")
        elif st.session_state.page == "Trash":
            all_notes_page("trash")
        elif st.session_state.page == "Settings":
            settings_page()
    else:
        apply_styles()
        login_page()


if __name__ == "__main__":
    main()
