"""
Modul: news_loader.py
Zweck:
Lädt Nachrichten aus RSS-Feeds und speichert sie in SQLite.
"""

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import feedparser
from datetime import datetime
from datetime import timezone

@dataclass
class NewsLoader:
    """Erstellt und verwaltet eine SQLite-Tabelle für Nachrichten."""

    db_path: Path

    def __post_init__(self):
        """Öffnet Verbindung und erstellt Tabelle 'news' falls nötig."""
        self.db_path = Path(self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.ensure_schema()

    def ensure_schema(self):
        """Erstellt Tabelle news falls nicht vorhanden."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                title TEXT,
                link TEXT UNIQUE,
                published_at TEXT,
                content TEXT
            );
        """)
        self.conn.commit()

    def fetch_and_upsert(self, url: str, source: str) -> int:
        """
        Lädt einen RSS-Feed (url), wandelt Einträge in einheitliche Felder um
        und speichert sie idempotent in der Tabelle 'news'.
        Rückgabe: Anzahl der betroffenen Zeilen.
        """
        import html
        import time

        feed = feedparser.parse(url)
        if feed.bozo:
            print(f"[WARN] Problem beim Parsen: {feed.bozo_exception}")
        entries = feed.entries or []
        if not entries:
            print(f"[INFO] Keine Einträge in Feed: {url}")
            return 0

        rows = []
        for e in entries:
            title = html.unescape(getattr(e, "title", "") or "").strip()
            link = getattr(e, "link", "") or ""
            # published_dt robust bestimmen
            if getattr(e, "published_parsed", None):
                ts = time.mktime(e.published_parsed)
                published_at = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            else:
                published_at = getattr(e, "published", "") or ""
            # Content/Text (fallbacks)
            content = ""
            if getattr(e, "summary", None):
                content = html.unescape(e.summary)
            if getattr(e, "content", None):
                # falls content[] vorhanden, nimm das erste Element
                try:
                    content = html.unescape(e.content[0].value or content)
                except Exception:
                    pass

            if not link:
                # ohne Link nicht speicherbar (UNIQUE link)
                continue

            rows.append((source, title, link, published_at, content))

        cur = self.conn.cursor()
        cur.executemany(
            """
            INSERT INTO news (source, title, link, published_at, content)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(link) DO UPDATE SET
                source=excluded.source,
                title=excluded.title,
                published_at=excluded.published_at,
                content=excluded.content;
            """,
            rows,
        )
        self.conn.commit()
        return cur.rowcount

    def close(self):
        """Schließt die DB-Verbindung."""
        self.conn.close()