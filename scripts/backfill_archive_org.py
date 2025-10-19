"""
Script: backfill_archive_org.py
Zweck:
- Lädt historische News-Homepage-Snapshots aus dem Internet Archive (PastPages)
  für mehrere Quellen und speichert sie in die existierende SQLite-Tabelle `news`.

Ausführen (im Projektwurzelordner):
    python scripts/backfill_archive_org.py
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import sys
import time
from urllib.parse import urlencode
import requests
import sqlite3
from typing import Iterable, List, Tuple, Dict, Any, Optional

# -------------------------------
# Pfad-Setup (src/ importierbar)
# -------------------------------
ROOT = Path(__file__).resolve().parents[1]  # Projektwurzel: hs2025_ml/
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.append(str(SRC))

from hs2025_ml.data.news_loader import NewsLoader  # nutzt dein bestehendes Schema

# -------------------------------
# KONFIGURATION
# -------------------------------
START_DATE = date(2015, 1, 1)
END_DATE   = date(2025, 12, 31)

# Label -> Freitextfilter für PastPages
SOURCES: List[Tuple[str, str]] = [
    ("Reuters",        "reuters"),
    ("Reuters (CN)",   '"reuters chinese" OR "reuters (chinese)" OR reuters chinese'),
    ("Bloomberg",      'bloomberg OR "bloomberg.com"'),
    ("Financial Times",'ft.com OR "financial times"'),
    ("WSJ",            'wsj.com OR "wall street journal"'),
    # Falls du BBC später willst:
    # ("BBC",            'bbc OR "bbc.com"'),
]

# Archive.org API
ARCHIVE_SEARCH_URL = "https://archive.org/advancedsearch.php"
FIELDS = ["identifier", "title", "date"]

# Abruf-Parameter
ROWS_PER_PAGE = 1000          # max. 1000 pro Seite
REQUEST_TIMEOUT_SEC = 30
MAX_RETRIES = 3               # pro Request
RETRY_BACKOFF_SEC = 3.0       # * Versuch_index (1,2,3, …)
POLITE_SLEEP_SEC = 0.25       # kurze Pause zwischen Requests


# -------------------------------
# Hilfsfunktionen
# -------------------------------
def build_query_pastpages(day_str: str, text_filter: str) -> str:
    """Query für PastPages-Snapshots an einem Tag."""
    # PastPages-Sammlung + Tagesfenster + Freitext (z.B. 'reuters', 'bloomberg', ...)
    return f'(collection:"pastpages") AND date:[{day_str} TO {day_str}] AND {text_filter}'


def _http_get_json(url: str, timeout: int) -> Dict[str, Any]:
    """HTTP GET mit Retries + JSON-Decode."""
    last_err: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SEC * attempt)
            else:
                raise
    # theoretisch unerreichbar
    raise last_err  # type: ignore[misc]


def query_archive_all_pages(q: str) -> List[Dict[str, Any]]:
    """
    Holt ALLE Seiten der Archive.org-Suche für eine Tages-Query.
    Gibt die gesammelten Docs (identifier, title, date, …) zurück.
    """
    page = 1
    all_docs: List[Dict[str, Any]] = []
    while True:
        params = {
            "q": q,
            "fl[]": FIELDS,
            "rows": ROWS_PER_PAGE,
            "page": page,
            "output": "json",
            "sort[]": "date asc",
        }
        url = f"{ARCHIVE_SEARCH_URL}?{urlencode(params, doseq=True)}"

        try:
            data = _http_get_json(url, timeout=REQUEST_TIMEOUT_SEC)
        except Exception as e:
            # hochreichen – der Aufrufer loggt den Fehler tag/sourcenspezifisch
            raise RuntimeError(f"HTTP/JSON fehlgeschlagen (Seite {page}): {e}")

        resp = data.get("response", {}) or {}
        docs = resp.get("docs", []) or []
        if not docs:
            break
        all_docs.extend(docs)

        # Heuristik: Wenn weniger als ROWS_PER_PAGE zurückkamen, sind wir am Ende
        if len(docs) < ROWS_PER_PAGE:
            break
        page += 1
        time.sleep(POLITE_SLEEP_SEC)
    return all_docs


def docs_to_rows(docs: Iterable[Dict[str, Any]], fallback_source: str) -> List[Tuple[str, str, str, str, str]]:
    """
    IA-Dokumente -> Zeilen für NewsLoader:
    (source, title, link, published_at, content)
    """
    out: List[Tuple[str, str, str, str, str]] = []
    for d in docs:
        identifier = (d.get("identifier") or "").strip()
        title      = (d.get("title") or "").strip()
        date_str   = (d.get("date") or "").strip()  # meist "YYYY-MM-DD HH:MM:SS" (UTC)
        if not identifier or not title or not date_str:
            continue
        link = f"https://archive.org/details/{identifier}"
        out.append((fallback_source, title, link, date_str, ""))  # content leer; wird später via Content-Fetcher gefüllt
    return out


def save_rows(loader: NewsLoader, rows: List[Tuple[str, str, str, str, str]]) -> int:
    """Idempotent in SQLite schreiben (UNIQUE link, ON CONFLICT UPDATE)."""
    if not rows:
        return 0
    cur = loader.conn.cursor()
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
    loader.conn.commit()
    return cur.rowcount


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


# -------------------------------
# Main
# -------------------------------
def main() -> None:
    db_path = ROOT / "db" / "fx_project.sqlite"
    loader = NewsLoader(db_path)
    total_all = 0

    try:
        for day in daterange(START_DATE, END_DATE):
            day_str = day.strftime("%Y-%m-%d")
            print(f"[INFO] {day_str} – lade archive.org (PastPages) …")

            for label, qtext in SOURCES:
                q = build_query_pastpages(day_str, qtext)
                try:
                    docs = query_archive_all_pages(q)
                    print(f"[DEBUG] {label}: Treffer = {len(docs)}")

                    saved = 0
                    if docs:
                        rows = docs_to_rows(docs, label)
                        saved = save_rows(loader, rows)
                    print(f"   → {label}: gespeichert/aktualisiert: {saved}")
                    total_all += saved

                except Exception as e:
                    print(f"[WARN] {label} @ {day_str}: {e}")

                time.sleep(POLITE_SLEEP_SEC)  # höflich zur API

    finally:
        loader.close()

    print(f"[SUCCESS] Gesamt gespeichert: {total_all}")


if __name__ == "__main__":
    main()