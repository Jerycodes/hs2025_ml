# src/hs2025_ml/data/gdelt_loader.py
"""
GDELTLoader: Holt Nachrichten-Metadaten aus dem öffentlichen BigQuery-Dataset
'gdelt-bq.gdeltv2.gkg' und speichert sie als News in unsere SQLite-DB (Tabelle 'news').

Warum BigQuery?
- Vollständiges, historisches News-Korpus (inkl. 2015 -> heute)
- Kostenfrei/Free-Tier bei unserem Volumen
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple
import sqlite3
from datetime import datetime, timedelta

from google.cloud import bigquery


@dataclass
class GDELTLoader:
    """Verbindet BigQuery (lesen) und SQLite (schreiben)."""

    db_path: Path                              # z. B. Path("db/fx_project.sqlite")
    gcp_project: str | None = None             # optional explizit setzen; sonst Default-Creds

    def __post_init__(self) -> None:
        # --- SQLite vorbereiten ---
        self.db_path = Path(self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self._ensure_news_table()

        # --- BigQuery Client vorbereiten ---
        # Hinweis: Wenn du die Warnung wegen "quota project" loswerden willst,
        # übergib hier explizit dein GCP-Projekt (self.gcp_project).
        self.bq = bigquery.Client(project=self.gcp_project) if self.gcp_project else bigquery.Client()

    # ---------------- SQLite ----------------

    def _ensure_news_table(self) -> None:
        """Legt Tabelle 'news' an (idempotent)."""
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

    def _upsert_rows(self, rows: List[Tuple[str, str, str, str, str]]) -> int:
        """
        Schreibt (source, title, link, published_at, content) idempotent in 'news'.
        link ist UNIQUE -> bestehendes wird aktualisiert (Upsert).
        """
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

    # ---------------- BigQuery ----------------

    @staticmethod
    def _day_bounds_yyyymmddhhmmss(d: datetime) -> tuple[int, int]:
        """Gibt (start_ts, end_ts) als Integer im GDELT-Format YYYYMMDDhhmmss zurück."""
        start = int(d.strftime("%Y%m%d") + "000000")
        end   = int(d.strftime("%Y%m%d") + "235959")
        return start, end

    def _query_gkg_day(self, d: datetime) -> Iterable[bigquery.table.Row]:
        """
        Holt alle GKG-Zeilen eines Tages, grob auf wirtschafts/finanznahe Themen gefiltert.
        Wichtige Felder:
          - DATE (yyyyMMddhhmmss, int)
          - SourceCommonName (Publisher-Name)
          - DocumentIdentifier (URL)
          - V2Themes (kommagetrennte Themen-Tags)
          - V2Tone (enthält Tone, aber hier ungenutzt)
          - V2Persons/V2Orgs/V2Locations (optional)
          - AllNames (enthält u.a. Sätze/Überschriften – als 'title'-Näherung)
        """
        start_ts, end_ts = self._day_bounds_yyyymmddhhmmss(d)

        # Themen-Filter: wir nehmen ECON/ECONOMY/FINANCE/BUSINESS/FOREX/CURRENCY/MARKET
        # (GDELT-Themes sind großschreibungsinsensitiv; wir verwenden LIKE)
        sql = """
        SELECT
          DATE,
          SourceCommonName AS source,
          DocumentIdentifier AS link,
          V2Themes,
          AllNames
        FROM `gdelt-bq.gdeltv2.gkg`
        WHERE DATE BETWEEN @start_ts AND @end_ts
          AND (
                LOWER(V2Themes) LIKE '%econ%'
             OR LOWER(V2Themes) LIKE '%econom%'
             OR LOWER(V2Themes) LIKE '%financ%'
             OR LOWER(V2Themes) LIKE '%business%'
             OR LOWER(V2Themes) LIKE '%market%'
             OR LOWER(V2Themes) LIKE '%forex%'
             OR LOWER(V2Themes) LIKE '%currenc%'
          )
        """
        job = self.bq.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("start_ts", "INT64", start_ts),
                    bigquery.ScalarQueryParameter("end_ts", "INT64", end_ts),
                ]
            ),
        )
        return job.result(page_size=2000)  # Iterator über Ergebnisse

    @staticmethod
    def _title_from_allnames(allnames: str | None) -> str:
        """
        Nimmt AllNames (ein zusammengesetztes Feld) und erzeugt eine kurze 'title'-Näherung.
        Heuristik: erstes Segment bis ';' oder max. 140 Zeichen.
        """
        if not allnames:
            return ""
        title = allnames.split(";")[0].strip()
        return title[:140]

    def fetch_day(self, d: datetime) -> int:
        """
        Lädt einen Tag aus GDELT (finanznahe Themen), formatiert Felder und upsertet in SQLite.
        Rückgabe: Anzahl gespeicherter/aktualisierter Zeilen.
        """
        rows_out: list[tuple[str, str, str, str, str]] = []
        for r in self._query_gkg_day(d):
            # published_at aus integerischem DATE-Feld erzeugen (UTC)
            dt_str = str(r["DATE"])          # z. B. 20150115001500
            dt = datetime.strptime(dt_str, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")

            source = r.get("source") or ""
            link   = r.get("link") or ""
            title  = self._title_from_allnames(r.get("AllNames"))
            content = ""  # GKG enthält keinen vollen Artikeltext – leer lassen, ggf. später scrapen

            if link:
                rows_out.append((source, title, link, dt, content))

        return self._upsert_rows(rows_out)

    def fetch_range(self, start: datetime, end: datetime, progress: bool = True) -> int:
        """
        Lädt inkl. beide Grenzen [start, end] Tag für Tag.
        Rückgabe: Summe der upserteten Zeilen.
        """
        total = 0
        d = start
        while d <= end:
            try:
                n = self.fetch_day(d)
                if progress:
                    print(f"[{d.date()}] +{n} Artikel")
                total += n
            except Exception as e:
                # Robustheit: wir loggen und fahren am nächsten Tag fort
                print(f"[WARN] GDELT request failed for {d.date()}: {e}")
            d += timedelta(days=1)
        if progress:
            print(f"[SUCCESS] Gesamt gespeichert: {total}")
        return total

    def close(self) -> None:
        """Schließt SQLite-Verbindung."""
        self.conn.close()