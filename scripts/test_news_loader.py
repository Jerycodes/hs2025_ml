"""
Testskript: Lädt einen RSS-Feed (Reuters Business) in die SQLite-DB.
Läuft robust, egal von wo gestartet (setzt den src/ Pfad dynamisch).
"""


from hs2025_ml.data.news_loader import NewsLoader


def main():
    nl = NewsLoader("db/fx_project.sqlite")
    rows = nl.fetch_and_upsert("https://feeds.bbci.co.uk/news/business/rss.xml", "Reuters")
    print(f"[TEST] {rows} News gespeichert.")
    nl.close()


if __name__ == "__main__":
    main()