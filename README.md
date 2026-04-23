# Smart Notepad Pro

Smart Notepad Pro is a polished, Python-only Streamlit notepad and productivity app built with SQLite, pandas, Plotly, and optional note encryption.

## Features

- Secure signup and login
- Per-user notes stored in SQLite
- Create, edit, archive, trash, restore, duplicate, and permanently delete notes
- Markdown and checklist note types
- Tags and folders
- Pinned, favorite, archived, trash, and color labels
- Version history with restore
- Locked notes with password protection and optional encryption
- Search, filter, and sorting controls
- Quick note creator in the sidebar
- Dashboard with metrics, charts, streak tracking, and recent activity
- Import/export in TXT, Markdown, JSON
- Database backup and restore
- Custom Streamlit styling

## Tech Stack

- Python
- Streamlit
- SQLite
- pandas
- Plotly
- hashlib for password hashing
- cryptography for note encryption

## Project Structure

- `app.py` - Streamlit application entry point
- `db.py` - SQLite schema, initialization, and storage helpers
- `auth.py` - Password hashing and authentication
- `notes.py` - Note operations, versioning, encryption, import/export
- `utils.py` - Formatting and helper functions
- `styles.py` - Custom CSS injection
- `seed.py` - Optional database seeding helper

## Setup

1. Create a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the app:

```bash
streamlit run app.py
```

## Demo Account

If the database is empty, Smart Notepad Pro seeds a demo account automatically.

- Username: `demo`
- Password: `demo12345`

## Notes

- Passwords are never stored in plain text.
- Encrypted notes require unlocking before export or editing.
- Database backups are saved under the `backups/` directory.

## Backup and Restore

Use the Settings page to:

- download a database backup
- restore from a backup file
- export all notes as JSON

## Sample Workflow

1. Sign up or log in.
2. Create a folder and a few tags.
3. Add notes from the sidebar quick note creator.
4. Use the editor to lock notes, preview Markdown, and inspect versions.
5. Open the Dashboard for charts, streaks, and activity.

## Database

The app initializes the following tables:

- `users`
- `folders`
- `tags`
- `notes`
- `note_tags`
- `note_versions`
- `activity_logs`
- `settings`

## License

This project is provided as a starter application for local use and customization.

