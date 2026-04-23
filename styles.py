"""Custom CSS for Smart Notepad Pro."""

from __future__ import annotations


def get_css(theme: str = "dark") -> str:
    dark = theme.lower() == "dark"
    if dark:
        bg = "#07111f"
        bg2 = "#0d1728"
        panel = "rgba(12, 18, 31, 0.84)"
        panel_border = "rgba(148, 163, 184, 0.18)"
        text = "#e5eefc"
        muted = "#94a3b8"
        accent = "#38bdf8"
        accent2 = "#f59e0b"
        shadow = "0 18px 42px rgba(0, 0, 0, 0.28)"
    else:
        bg = "#f5f7fb"
        bg2 = "#eaf1ff"
        panel = "rgba(255, 255, 255, 0.9)"
        panel_border = "rgba(15, 23, 42, 0.08)"
        text = "#0f172a"
        muted = "#475569"
        accent = "#0284c7"
        accent2 = "#d97706"
        shadow = "0 18px 42px rgba(15, 23, 42, 0.10)"

    return f"""
    <style>
    :root {{
        --sn-bg: {bg};
        --sn-bg2: {bg2};
        --sn-panel: {panel};
        --sn-panel-border: {panel_border};
        --sn-text: {text};
        --sn-muted: {muted};
        --sn-accent: {accent};
        --sn-accent2: {accent2};
        --sn-shadow: {shadow};
        --sn-radius: 20px;
    }}

    html, body, [class*="css"] {{
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}

    .stApp {{
        background:
            radial-gradient(circle at top right, rgba(56, 189, 248, 0.18), transparent 28%),
            radial-gradient(circle at bottom left, rgba(245, 158, 11, 0.14), transparent 26%),
            linear-gradient(160deg, var(--sn-bg), var(--sn-bg2));
        color: var(--sn-text);
    }}

    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02));
        border-right: 1px solid var(--sn-panel-border);
    }}

    [data-testid="stHeader"] {{
        background: transparent;
    }}

    #MainMenu, footer {{
        visibility: hidden;
    }}

    .sn-hero {{
        background: linear-gradient(135deg, rgba(56, 189, 248, 0.18), rgba(245, 158, 11, 0.12));
        border: 1px solid var(--sn-panel-border);
        border-radius: 28px;
        padding: 1.25rem 1.4rem;
        box-shadow: var(--sn-shadow);
        backdrop-filter: blur(12px);
        margin-bottom: 1rem;
    }}

    .sn-hero h1, .sn-hero p, .sn-card, .sn-note-meta, .sn-muted {{
        color: var(--sn-text);
    }}

    .sn-muted {{
        color: var(--sn-muted);
    }}

    .sn-card {{
        background: var(--sn-panel);
        border: 1px solid var(--sn-panel-border);
        border-radius: var(--sn-radius);
        padding: 1rem 1rem 0.85rem 1rem;
        box-shadow: var(--sn-shadow);
        margin-bottom: 0.9rem;
    }}

    .sn-card:hover {{
        transform: translateY(-1px);
        transition: all 0.2s ease;
        border-color: rgba(56, 189, 248, 0.45);
    }}

    .sn-note-title {{
        font-size: 1.05rem;
        font-weight: 700;
        margin-bottom: 0.35rem;
    }}

    .sn-badges {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.35rem;
        margin: 0.5rem 0;
    }}

    .sn-badge {{
        display: inline-flex;
        align-items: center;
        gap: 0.25rem;
        padding: 0.25rem 0.6rem;
        border-radius: 999px;
        border: 1px solid var(--sn-panel-border);
        background: rgba(148, 163, 184, 0.10);
        font-size: 0.78rem;
        color: var(--sn-muted);
    }}

    .sn-chip {{
        display: inline-block;
        padding: 0.2rem 0.55rem;
        border-radius: 999px;
        font-size: 0.74rem;
        font-weight: 700;
        margin-right: 0.35rem;
        color: white;
    }}

    .sn-metric {{
        background: var(--sn-panel);
        border: 1px solid var(--sn-panel-border);
        border-radius: 18px;
        padding: 0.9rem 1rem;
        box-shadow: var(--sn-shadow);
    }}

    .sn-empty {{
        border: 1px dashed var(--sn-panel-border);
        border-radius: 20px;
        padding: 1.4rem;
        text-align: center;
        color: var(--sn-muted);
        background: rgba(148, 163, 184, 0.08);
    }}

    .sn-focus-shell {{
        max-width: 1060px;
        margin: 0 auto;
    }}

    div[data-baseweb="textarea"] textarea {{
        min-height: 340px;
        line-height: 1.6;
    }}

    div[data-testid="stMetric"] {{
        background: var(--sn-panel);
        border: 1px solid var(--sn-panel-border);
        border-radius: 18px;
        padding: 0.4rem 0.7rem;
        box-shadow: var(--sn-shadow);
    }}

    .stButton button {{
        border-radius: 12px;
        border: 1px solid rgba(56, 189, 248, 0.35);
        background: linear-gradient(135deg, rgba(56, 189, 248, 0.14), rgba(245, 158, 11, 0.10));
        color: var(--sn-text);
        font-weight: 650;
    }}

    .stDownloadButton button {{
        border-radius: 12px;
    }}

    .stTabs [data-baseweb="tab-list"] {{
        gap: 0.4rem;
    }}

    .stTabs [data-baseweb="tab"] {{
        border-radius: 999px;
        background: rgba(148, 163, 184, 0.12);
        padding: 0.5rem 0.9rem;
    }}

    .stTabs [aria-selected="true"] {{
        background: rgba(56, 189, 248, 0.18);
    }}

    .sn-section-title {{
        font-weight: 800;
        letter-spacing: 0.01em;
        margin: 0.25rem 0 0.55rem 0;
    }}

    .sn-inline-panel {{
        background: rgba(148, 163, 184, 0.08);
        border: 1px solid var(--sn-panel-border);
        border-radius: 18px;
        padding: 0.8rem 0.9rem;
    }}
    </style>
    """

