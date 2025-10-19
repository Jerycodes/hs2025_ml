# scripts/fix_pastpages_sources.py
"""
Normalisiert alte 'pastpages.org'-Einträge in der Tabelle 'news' auf echte Quellen.
- Reuters
- Reuters (CN)
- Bloomberg
- Financial Times
- WSJ

Ausführung:
    python scripts/fix_pastpages_sources.py
"""

import sqlite3
from pathlib import Path
from textwrap import dedent

DB_PATH = Path("db/fx_project.sqlite")

def run():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    print(f"[INFO] Verbunden mit {DB_PATH}")

    # 1) Reuters (Englisch)
    cur.execute(dedent("""
        UPDATE news
           SET source = 'Reuters'
         WHERE source = 'pastpages.org'
           AND (
                 title LIKE '%Reuters at %' OR
                 link  LIKE '%pastpages-reuters-%'
               );
    """))
    print(f"[FIX] Reuters: {cur.rowcount} Zeilen aktualisiert.")

    # 2) Reuters (Chinese)
    cur.execute(dedent("""
        UPDATE news
           SET source = 'Reuters (CN)'
         WHERE source = 'pastpages.org'
           AND (
                 title LIKE '%Reuters (Chinese)%' OR
                 link  LIKE '%pastpages-reuters-chinese-%'
               );
    """))
    print(f"[FIX] Reuters (CN): {cur.rowcount} Zeilen aktualisiert.")

    # 3) Bloomberg
    cur.execute(dedent("""
        UPDATE news
           SET source = 'Bloomberg'
         WHERE source = 'pastpages.org'
           AND (
                 title LIKE '%Bloomberg%' OR
                 link  LIKE '%pastpages-bloomberg-%'
               );
    """))
    print(f"[FIX] Bloomberg: {cur.rowcount} Zeilen aktualisiert.")

    # 4) Financial Times
    cur.execute(dedent("""
        UPDATE news
           SET source = 'Financial Times'
         WHERE source = 'pastpages.org'
           AND (
                 title LIKE '%Financial Times%' OR
                 link  LIKE '%financial-times%' OR
                 link  LIKE '%ft.com%'
               );
    """))
    print(f"[FIX] Financial Times: {cur.rowcount} Zeilen aktualisiert.")

    # 5) Wall Street Journal
    cur.execute(dedent("""
        UPDATE news
           SET source = 'WSJ'
         WHERE source = 'pastpages.org'
           AND (
                 title LIKE '%WSJ%' OR
                 title LIKE '%Wall Street Journal%' OR
                 link  LIKE '%wsj.com%' OR
                 link  LIKE '%wall-street-journal%'
               );
    """))
    print(f"[FIX] WSJ: {cur.rowcount} Zeilen aktualisiert.")

    conn.commit()

    # Kurze Übersicht
    cur.execute("""
        SELECT source, COUNT(*) AS n
          FROM news
         GROUP BY source
         ORDER BY n DESC;
    """)
    rows = cur.fetchall()

    print("\n[SUMMARY] Quellenübersicht nach Fix:")
    for s, n in rows:
        print(f"  {s:16s} {n}")

    conn.close()
    print("\n[DONE] Fertig.")

if __name__ == "__main__":
    run()