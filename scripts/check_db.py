#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Quick DB Check for hs2025_ml
- zeigt Gesamtzeilen, Zeitraum, pro-Quelle-Zählung und DB-Dateigröße
Ausführen:  python scripts/check_db.py
"""

import os
import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path("db/fx_project.sqlite")

def human_size(n):
    for unit in ["B","KB","MB","GB","TB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"

def main():
    if not DB_PATH.exists():
        print("❌ DB-Datei nicht gefunden:", DB_PATH)
        return

    print("📦 DB:", DB_PATH)
    print("📏 Größe:", human_size(os.path.getsize(DB_PATH)))

    conn = sqlite3.connect(DB_PATH)
    # Schnellere Aggregationen
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")

    total = pd.read_sql_query("SELECT COUNT(*) AS n FROM news;", conn).iloc[0]["n"]
    print("🧮 Zeilen in news:", total)

    rng = pd.read_sql_query("""
        SELECT MIN(published_at) AS min_dt,
               MAX(published_at) AS max_dt
        FROM news
        WHERE published_at IS NOT NULL AND published_at <> '';
    """, conn)
    print("🗓️ Zeitraum:", rng.iloc[0]["min_dt"], "→", rng.iloc[0]["max_dt"])

    sources = pd.read_sql_query("""
        SELECT source, COUNT(*) AS n
        FROM news
        GROUP BY source
        ORDER BY n DESC
        LIMIT 20;
    """, conn)
    conn.close()

    print("\n🔝 Top-Quellen:")
    print(sources.to_string(index=False))

if __name__ == "__main__":
    main()