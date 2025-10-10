from dataclasses import dataclass
from pathlib import Path
import sqlite3
import pandas as pd
import yfinance as yf

@dataclass
class FXDataLoader:
    """Erstellt und verwaltet eine SQLite-Datenbank für FX-Kurse."""

    db_path: Path  # z. B. Path("db/fx_project.sqlite")

    def __post_init__(self) -> None:
        """Beim Erzeugen der Klasse wird automatisch die DB geöffnet
        und das Schema (fx_rates) erstellt, falls es noch nicht existiert.
        """
        # Pfad sicherstellen
        self.db_path = Path(self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Verbindung aufbauen
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")

        # Tabelle erzeugen (falls noch nicht vorhanden)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        """Erstellt die Tabelle fx_rates (falls nicht vorhanden)."""
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fx_rates (
                ticker TEXT NOT NULL,
                date   TEXT NOT NULL,
                open   REAL,
                high   REAL,
                low    REAL,
                close  REAL,
                volume REAL,
                PRIMARY KEY (ticker, date)
            );
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fx_rates_date ON fx_rates(date);"
        )
        self.conn.commit()

    def download(self, ticker: str, start: str, end: str | None = None, interval: str = "1d"):
        """
        Lädt FX-Daten via yfinance und gibt ein *flaches* DataFrame zurück
        (Spalten: date, open, high, low, close, volume).
        Behandelt den Fall, dass yfinance MultiIndex-Spalten liefert.
        """
        import pandas as pd
        import yfinance as yf

        # 1) Daten von Yahoo Finance holen
        df = yf.download(
            ticker, start=start, end=end, interval=interval,
            progress=False, auto_adjust=False,
        )

        # 2) Nichts gefunden? -> leeres DF zurück
        if df.empty:
            print(f"[WARN] Keine Daten für {ticker} gefunden.")
            return df

        # 3) Falls yfinance MultiIndex-Spalten liefert (z.B. ('Open','eurusd=x')):
        if isinstance(df.columns, pd.MultiIndex):
            # alle Symbole der letzten Ebene einsammeln (Reihenfolge beibehalten)
            last_level = df.columns.get_level_values(-1)
            symbols = list(dict.fromkeys(map(str, last_level)))

            # a) exakter Treffer?
            if ticker in last_level:
                df = df.xs(ticker, axis=1, level=-1, drop_level=True)
            else:
                # b) case-insensitive Treffer?
                match = next((s for s in symbols if s.lower() == ticker.lower()), None)
                if match is not None:
                    df = df.xs(match, axis=1, level=-1, drop_level=True)
                else:
                    # c) wenn nur EIN Symbol vorhanden ist -> Ebene droppen
                    if len(set(symbols)) == 1:
                        df.columns = df.columns.droplevel(-1)
                    else:
                        raise KeyError(f"Ticker {ticker!r} nicht in Spalten gefunden. Vorhanden: {symbols}")

        # 4) Spalten vereinheitlichen & Datumsspalte erzeugen
        df = df.rename(columns=str.lower)  # Open->open etc.
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df["date"] = df.index.strftime("%Y-%m-%d")

        # 5) Nur benötigte Spalten bereitstellen (fehlende ergänzen)
        cols = ["date", "open", "high", "low", "close", "volume"]
        for c in cols:
            if c not in df.columns:
                df[c] = None

        # 6) Flaches, speicherfertiges DF zurückgeben
        return df[cols].reset_index(drop=True)

    def upsert(self, ticker: str, df: pd.DataFrame) -> int:
        """Schreibt Daten idempotent in SQLite (überschreibt vorhandene Zeilen)."""
        if df.empty:
            return 0

        rows = [
            (
                ticker,
                row["date"],
                float(row["open"]) if pd.notna(row["open"]) else None,
                float(row["high"]) if pd.notna(row["high"]) else None,
                float(row["low"]) if pd.notna(row["low"]) else None,
                float(row["close"]) if pd.notna(row["close"]) else None,
                float(row["volume"]) if pd.notna(row["volume"]) else None,
            )
            for _, row in df.iterrows()
        ]

        cur = self.conn.cursor()
        cur.executemany(
            """
            INSERT INTO fx_rates (ticker, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, date) DO UPDATE SET
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                volume=excluded.volume;
            """,
            rows,
        )
        self.conn.commit()
        return cur.rowcount

    def latest_date(self, ticker: str) -> str | None:
        """Gibt das zuletzt gespeicherte Datum (YYYY-MM-DD) für einen Ticker zurück."""
        cur = self.conn.execute("SELECT MAX(date) FROM fx_rates WHERE ticker = ?;", (ticker,))
        row = cur.fetchone()
        return row[0] if row and row[0] else None

    def close(self) -> None:
        """Schließt die Datenbankverbindung."""
        self.conn.close()
