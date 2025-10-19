# src/hs2025_ml/data/ia_loader.py
"""
Internet Archive (archive.org) Loader
------------------------------------
Holt Nachrichten-Metadaten aus Archive.org (Advanced Search API) und speichert
sie idempotent in unsere SQLite-News-Tabelle (über den vorhandenen NewsLoader).

Hinweis:
- Wir holen Metadaten (Titel/Datum/Link). Volltexte sind je nach Item-Typ uneinheitlich.
- Quelle (source) wird aus identifier/title/creator hergeleitet (Reuters, Bloomberg, WSJ, FT).
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, List, Tuple, Optional
from urllib.parse import urlencode
import requests
import time

from hs2025_ml.data.news_loader import NewsLoader

ARCHIVE_SEARCH_URL = "https://archive.org/advancedsearch.php"


@dataclass
class ArchiveSearchConfig:
    """
    Konfiguration für die IA-Suche.
    - collections: gezielte Sammlungen (z. B. 'pastpages' enthält Nachrichten-Homepages)
    - sources: optionale Freitext-Begriffe (z. B. 'reuters'), können leer bleiben
    """
    collections: List[str] | None = None
    sources: List[str] | None = None
    rows_per_page: int = 500  # max 1000

    def __post_init__(self):
        if self.collections is None:
            # Für konsistente Treffer: pastpages ist sehr ergiebig
            self.collections = ["pastpages"]
        if self.sources is None:
            self.sources = []


def _build_query(config: ArchiveSearchConfig, start_date: str, end_date: str) -> str:
    """
    Baut die IA-Query (Solr-Syntax):
      (collection:"...") AND date:[YYYY-MM-DD TO YYYY-MM-DD] AND <optional sources>
    """
    parts: List[str] = []

    if config.collections:
        parts.append("(" + " OR ".join([f'collection:"{c}"' for c in config.collections]) + ")")

    parts.append(f"date:[{start_date} TO {end_date}]")

    if config.sources:
        parts.append("(" + " OR ".join(config.sources) + ")")

    return " AND ".join(parts)


def _query_archive(
    q: str,
    rows: int = 500,
    page: int = 1,
    fields: Optional[List[str]] = None,
) -> dict:
    """
    Führt eine Advanced-Search-Anfrage aus und liefert das JSON zurück.
    """
    if fields is None:
        fields = ["identifier", "title", "date", "creator", "collection", "mediatype"]

    params = {
        "q": q,
        "fl[]": fields,
        "rows": rows,
        "page": page,
        "output": "json",
        "sort[]": "date desc",
    }
    url = f"{ARCHIVE_SEARCH_URL}?{urlencode(params, doseq=True)}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _guess_source_from_doc(d: dict) -> str:
    """
    Leitet eine Marke (Reuters, Reuters (CN), Bloomberg, WSJ, Financial Times) aus dem
    identifier/title/creator ab. Fällt auf 'archive.org' zurück.
    """
    ident = (d.get("identifier") or "").lower()
    title = (d.get("title") or "").lower()
    creator = (d.get("creator") or "").lower()

    # pastpages: identifier enthält die Marke zuverlässig
    if "pastpages-reuters-chinese" in ident:
        return "Reuters (CN)"
    if "pastpages-reuters" in ident:
        return "Reuters"
    if "pastpages-bloomberg" in ident:
        return "Bloomberg"
    if "pastpages-wsj" in ident:
        return "WSJ"
    if "pastpages-ft" in ident:
        return "Financial Times"

    # weiche Fallbacks
    if "wall street journal" in title or "wsj" in title:
        return "WSJ"
    if "financial times" in title or "ft.com" in title:
        return "Financial Times"
    if "bloomberg" in title or "bloomberg" in creator:
        return "Bloomberg"
    if "reuters" in title or "reuters" in creator:
        return "Reuters"

    return "archive.org"


def _as_rows_for_newsloader(docs: Iterable[dict]) -> List[Tuple[str, str, str, str, str]]:
    """
    Wandelt IA-Dokumente in NewsLoader-Zeilen um:
      (source, title, link, published_at, content)
    """
    rows: List[Tuple[str, str, str, str, str]] = []
    for d in docs:
        identifier = (d.get("identifier") or "").strip()
        title = (d.get("title") or "").strip()
        date = (d.get("date") or "").strip()  # häufig 'YYYY-MM-DD'
        if not identifier or not title or not date:
            continue

        link = f"https://archive.org/details/{identifier}"
        source = _guess_source_from_doc(d)
        rows.append((source, title, link, date, ""))  # content leer (optional später nachladen)
    return rows


def fetch_and_store_from_archive(
    db_path: str,
    start_date: str,
    end_date: str,
    config: Optional[ArchiveSearchConfig] = None,
    max_pages: int = 20,
    sleep_sec: float = 0.8,
) -> int:
    """
    Holt Metadaten aus IA im Datumsbereich [start_date..end_date] und speichert sie in SQLite.

    Parameter:
    - db_path: Pfad zur SQLite (z. B. "db/fx_project.sqlite")
    - start_date/end_date: 'YYYY-MM-DD'
    - config: ArchiveSearchConfig (Sammlungen/Source-Begriffe)
    - max_pages: Sicherheitslimit gegen zu viele Seiten
    - sleep_sec: kleine Pause zwischen Requests

    Rückgabe:
    - Anzahl gespeicherter/aktualisierter Datensätze
    """
    if config is None:
        config = ArchiveSearchConfig()

    q = _build_query(config, start_date, end_date)

    loader = NewsLoader(db_path)
    total_saved = 0

    try:
        for page in range(1, max_pages + 1):
            data = _query_archive(q, rows=config.rows_per_page, page=page)
            response = data.get("response", {})
            docs = response.get("docs", [])
            num_found = response.get("numFound", 0)

            if not docs:
                break

            rows = _as_rows_for_newsloader(docs)

            # Bulk-Upsert direkt per SQL (idempotent via ON CONFLICT(link))
            cur = loader.conn.cursor()
            cur.executemany(
                """
                INSERT INTO news (source, title, link, published_at, content)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(link) DO UPDATE SET
                    source       = excluded.source,
                    title        = excluded.title,
                    published_at = excluded.published_at,
                    content      = excluded.content;
                """,
                rows,
            )
            loader.conn.commit()
            total_saved += cur.rowcount

            # Ende wenn alles geholt
            if page * config.rows_per_page >= num_found:
                break

            time.sleep(sleep_sec)
    finally:
        loader.close()

    return total_saved