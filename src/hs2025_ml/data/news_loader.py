"""
Modul: news_loader.py
Zweck:
- RSS/Atom-Feeds laden (robust über HTTPS)
- Einträge vereinheitlichen (source, title, link, published_at, content)
- Idempotent in SQLite-Tabelle 'news' speichern (UNIQUE: link)
"""

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
import sqlite3
import html
import time

import requests      # robustes HTTP(S)-Laden
import certifi       # aktuelles CA-Zertifikatsbundle
import feedparser    # RSS/Atom-Parser


@dataclass
class NewsLoader:
    """Verbindet zur SQLite-DB und stellt Lade-/Speicherfunktionen für News bereit."""
    db_path: Path  # z. B. Path("db/fx_project.sqlite")

    def __post_init__(self) -> None:
        # Pfad vorbereiten und DB-Verbindung herstellen
        self.db_path = Path(self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        """Erstellt die Tabelle 'news' (falls nicht vorhanden)."""
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                title TEXT,
                link TEXT UNIQUE,
                published_at TEXT,
                content TEXT
            );
            """
        )
        self.conn.commit()

    def _download_feed(self, url: str) -> feedparser.FeedParserDict:
        """
        Lädt den Feed-Text via HTTPS (requests + certifi) und parsed ihn mit feedparser.
        Dadurch umgehen wir typische SSL/Proxy-Probleme.
        """
        resp = requests.get(
            url,
            timeout=20,
            verify=certifi.where(),
            headers={"User-Agent": "hs2025-ml/1.0 (+https://example.local)"},  # netter UA
        )
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)
        if getattr(feed, "bozo", False):
            # bozo True ⇒ Parser hatte einen Fehler/Hinweis (nicht zwingend fatal)
            print(f"[WARN] Parser-Hinweis bei {url}: {getattr(feed, 'bozo_exception', '')}")
        return feed

    def fetch_and_upsert(self, url: str, source: str) -> int:
        """
        Lädt einen RSS/Atom-Feed, transformiert in einheitliche Felder
        und schreibt/updatet Einträge idempotent in 'news'.
        Rückgabe: Anzahl eingefügter/aktualisierter Zeilen.
        """
        try:
            feed = self._download_feed(url)
        except Exception as ex:
            print(f"[WARN] Download-Problem bei {url}: {ex}")
            return 0

        entries = getattr(feed, "entries", []) or []
        if not entries:
            print(f"[INFO] Keine Einträge in Feed: {url}")
            return 0

        rows: list[tuple[str, str, str, str, str]] = []
        for e in entries:
            title = html.unescape(getattr(e, "title", "") or "").strip()
            link = getattr(e, "link", "") or ""
            if not link:
                # ohne stabilen Link kein Upsert
                continue

            # Publikationszeit robust bestimmen
            if getattr(e, "published_parsed", None):
                ts = time.mktime(e.published_parsed)  # Zeitstempel aus struct_time
                published_at = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            else:
                # Fallback: rohe published-Zeichenkette (falls vorhanden), sonst leer
                published_at = (getattr(e, "published", "") or "").strip()

            # Content/Text mit Fallbacks
            content = ""
            if getattr(e, "summary", None):
                content = html.unescape(e.summary)
            if getattr(e, "content", None):
                try:
                    # e.content ist oft eine Liste mit Objekten {value, type, ...}
                    content = html.unescape(e.content[0].get("value") or content)
                except Exception:
                    pass

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

    def close(self) -> None:
        """Schließt die DB-Verbindung."""
        self.conn.close()