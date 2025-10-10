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
        """Lädt Kursdaten via yfinance und gibt ein bereinigtes DataFrame zurück."""
        df = yf.download(
            ticker,
            start=start,
            end=end,
            interval=interval,
            progress=False,
            auto_adjust=False,
        )
        if df.empty:
            print(f"[WARN] Keine Daten für {ticker} gefunden.")
            return df

        # Spaltennamen vereinheitlichen (alles klein)
        df = df.rename(columns=str.lower)

        # Index (DatetimeIndex) in Spalte 'date' konvertieren
        df["date"] = pd.to_datetime(df.index).strftime("%Y-%m-%d")

        # Reset für sauberen Index
        df = df.reset_index(drop=True)

        return df[["date", "open", "high", "low", "close", "volume"]]

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

    def close(self) -> None:
        """Schließt die Datenbankverbindung."""
        self.conn.close()
