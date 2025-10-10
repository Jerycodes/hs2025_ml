"""
Script: load_fx_data.py
Zweck:
Automatisiertes und *inkrementelles* Laden & Speichern von FX-Daten (EURUSD=X)
in die SQLite-Datenbank über die Klasse FXDataLoader.
"""

from datetime import datetime, timedelta
from datetime import timezone
from hs2025_ml.data.fx_loader import FXDataLoader


def main():
    ticker = "EURUSD=X"
    db_path = "../db/fx_project.sqlite"

    print(f"[INFO] Initialisiere FXDataLoader → {db_path}")
    loader = FXDataLoader(db_path)

    # 1) Prüfen, bis zu welchem Datum bereits Daten vorliegen
    last = loader.latest_date(ticker)
    if last:
        # ab dem Tag NACH dem letzten gespeicherten Datum nachladen
        start_dt = datetime.strptime(last, "%Y-%m-%d").date() + timedelta(days=1)
        print(f"[INFO] Bereits vorhanden bis {last}. Lade neu ab {start_dt}.")
    else:
        # Erstlauf
        start_dt = datetime(2015, 1, 1).date()
        print(f"[INFO] Keine vorhandenen Daten. Erstlauf ab {start_dt}.")

    # 2) Enddatum = heute (UTC-Date, ohne Zeit)
    end_dt = datetime.now(timezone.utc).date()
    if start_dt > end_dt:
        print("[INFO] Nichts zu laden (Daten sind bereits aktuell).")
        loader.close()
        return

    # 3) Download & Persistenz
    print(f"[INFO] Lade {ticker} von {start_dt} bis {end_dt} ...")
    df = loader.download(ticker, start=start_dt.isoformat(), end=end_dt.isoformat())

    print(f"[INFO] {len(df)} Zeilen geladen. Speichere in Datenbank ...")
    rows = loader.upsert(ticker, df)

    print(f"[SUCCESS] {rows} Zeilen gespeichert. Fertig.")
    loader.close()


if __name__ == "__main__":
    main()