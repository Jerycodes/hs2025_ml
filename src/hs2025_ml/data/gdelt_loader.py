"""
gdelt_loader.py — Lädt historische Finanznachrichten über die GDELT DOC 2.0 API
und speichert sie in der Tabelle 'news' in fx_project.sqlite.
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
import sqlite3
import requests

# GDELT API-Endpunkt
GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"


@dataclass
class GDELTLoader:
    """
    Lädt historische Nachrichten-Metadaten aus der GDELT DOC 2.0 API
    und speichert sie in die bestehende SQLite-Tabelle 'news'.
    """

    db_path: Path

    def __post_init__(self) -> None:
        """Verbindet sich mit der SQLite-Datenbank."""
        self.db_path = Path(self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")

    def _upsert_rows(self, rows: list[tuple]) -> int:
        """Schreibt (source, title, link, published_at, content) idempotent in 'news'."""
        if not rows:
            return 0
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

    def fetch_range(
        self,
        query: str,
        start_dt: datetime,
        end_dt: datetime,
        maxrecords: int = 250,
        source_label: str = "GDELT",
        allowed_domains: list[str] | None = None,
    ) -> int:
        """
        Lädt Artikel-Metadaten (Titel, Link, Zeitstempel, Auszug) aus der
        GDELT DOC 2.0 API im gegebenen Zeitraum und speichert sie in SQLite.

        Parameter:
        - query: Suchausdruck (z. B. 'EURUSD OR Euro OR ECB OR "European Central Bank"')
        - start_dt / end_dt: Start- und Endzeitpunkt im UTC-Zeitformat
        - maxrecords: Maximale Anzahl an Artikeln pro Anfrage (GDELT-Limit ~250)
        - source_label: Bezeichnung der Quelle (z. B. "GDELT" oder "Reuters via GDELT")
        - allowed_domains: Liste vertrauenswürdiger Domains (Whitelisting)
        """
        import urllib.parse

        # 1️⃣ Anfrageparameter vorbereiten
        params = {
            "query": query,
            "mode": "ArtList",
            "maxrecords": str(maxrecords),
            "format": "json",
            "startdatetime": start_dt.strftime("%Y%m%d%H%M%S"),
            "enddatetime": end_dt.strftime("%Y%m%d%H%M%S"),
        }

        # 2️⃣ HTTP-Anfrage an GDELT
        r = requests.get(GDELT_DOC_API, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        articles = data.get("articles", [])

        rows: list[tuple] = []

        for article in articles:
            title = (article.get("title") or "").strip()
            link = article.get("url") or ""
            if not link:
                continue

            # 3️⃣ Domainfilter für hochwertige Quellen
            if allowed_domains:
                netloc = urllib.parse.urlparse(link).netloc.lower()
                if netloc.startswith("www."):
                    netloc = netloc[4:]
                if not any(netloc == d or netloc.endswith("." + d) for d in allowed_domains):
                    continue

            # 4️⃣ Zeitstempel konvertieren
            seen = article.get("seendate") or ""
            try:
                published_at = datetime.strptime(seen, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                published_at = ""

            # 5️⃣ Kurztext (Excerpt)
            content = article.get("excerpt") or ""

            # 6️⃣ Zeile vorbereiten
            rows.append((source_label, title, link, published_at, content))

        # 7️⃣ Speichern
        inserted = self._upsert_rows(rows)
        return inserted

    def close(self) -> None:
        """Schließt die Datenbankverbindung."""
        self.conn.close()