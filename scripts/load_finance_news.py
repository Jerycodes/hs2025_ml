"""
Script: load_finance_news.py
-----------------------------------
Dieses Skript lädt aktuelle Finanznachrichten aus mehreren RSS-Feeds
(z. B. BBC, CNBC, Investing.com, FXStreet, MarketWatch)
und speichert sie in deiner SQLite-Datenbank (fx_project.sqlite).

Ziel:
- Automatisches Sammeln neuer News aus mehreren Quellen
- Speichern in der Tabelle 'news' (ohne Duplikate)
- Grundlage für spätere Verknüpfung mit FX-Daten
"""

# Pfad-Funktionen für Datenbankzugriff
from pathlib import Path

# Wir verwenden den NewsLoader, den du bereits in src/hs2025_ml/data/news_loader.py erstellt hast.
# Er kümmert sich um das Laden (über HTTPS) und Speichern (in SQLite).
from hs2025_ml.data.news_loader import NewsLoader


# ------------------------------
# 1️⃣ Pfad zur Datenbank
# ------------------------------
DB = "db/fx_project.sqlite"  # relativer Pfad zur SQLite-Datenbank


# ------------------------------
# 2️⃣ Liste von RSS-Feeds (URL + Name)
# ------------------------------
# Jeder Eintrag ist ein Tupel: (Feed-URL, Quellenname)
# Diese Feeds sind öffentlich und liefern meist die letzten 50–100 Artikel.
FEEDS = [
    ("https://feeds.bbci.co.uk/news/business/rss.xml", "BBC"),
    ("https://www.investing.com/rss/news_25.rss", "Investing.com"),
    ("https://www.cnbc.com/id/100003114/device/rss/rss.html", "CNBC"),
    ("https://www.fxstreet.com/rss/news", "FXStreet"),
    ("https://www.marketwatch.com/feeds/topstories", "MarketWatch"),
]


# ------------------------------
# 3️⃣ Hauptfunktion
# ------------------------------
def main():
    # NewsLoader-Objekt initialisieren (stellt Verbindung zur DB her)
    nl = NewsLoader(DB)

    # Zähler für alle gespeicherten Artikel
    total = 0

    # Durch alle definierten RSS-Feeds iterieren
    for url, source in FEEDS:
        print(f"[INFO] Lade Feed von {source}...")

        try:
            # Feed laden + in SQLite speichern
            # fetch_and_upsert() gibt die Anzahl der gespeicherten/aktualisierten Zeilen zurück
            rows = nl.fetch_and_upsert(url, source)
            print(f"  → {rows} neue oder aktualisierte Artikel gespeichert.")
            total += rows

        except Exception as e:
            # Falls z. B. ein Feed temporär nicht erreichbar ist
            print(f"[WARN] Fehler bei {source}: {e}")

    # Verbindung schließen (wichtig!)
    nl.close()

    # Zusammenfassung
    print(f"[SUCCESS] Gesamt: {total} Artikel gespeichert.")


# ------------------------------
# 4️⃣ Script-Startpunkt
# ------------------------------
# Diese Zeile stellt sicher, dass 'main()' nur ausgeführt wird,
# wenn du das Script direkt startest (nicht beim Import).
if __name__ == "__main__":
    main()