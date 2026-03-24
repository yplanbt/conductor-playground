import json
import aiosqlite
from app.config import settings

DB_PATH = settings.database_url


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    db = await get_db()
    try:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                search_id INTEGER,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                published_date TEXT,
                source TEXT,
                state TEXT,
                gender TEXT,
                crime_type TEXT,
                sentence_details TEXT,
                snippet TEXT,
                full_text TEXT,
                fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                search_params TEXT NOT NULL,
                query_used TEXT,
                result_count INTEGER,
                executed_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS saved_searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                search_params TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS google_sheets_tracker (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spreadsheet_id TEXT NOT NULL,
                spreadsheet_url TEXT NOT NULL,
                article_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                filled_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_articles_url ON articles(url);
        """)
        # Migrations for new columns
        for col in [
            "source_type TEXT",
            "defendant_name TEXT",
            "victim_name TEXT",
            "case_summary TEXT",
            "quality_score INTEGER",
            "is_sentencing INTEGER",
            "ai_fingerprint TEXT",
        ]:
            try:
                await db.execute(f"ALTER TABLE articles ADD COLUMN {col}")
            except Exception:
                pass
        try:
            await db.execute("CREATE INDEX IF NOT EXISTS idx_articles_defendant ON articles(defendant_name)")
        except Exception:
            pass
        await db.commit()
    finally:
        await db.close()


async def save_search_history(search_params: dict, query_used: str, result_count: int) -> int:
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO search_history (search_params, query_used, result_count) VALUES (?, ?, ?)",
            (json.dumps(search_params), query_used, result_count),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def save_articles(search_id: int, articles: list[dict]):
    db = await get_db()
    try:
        for a in articles:
            await db.execute(
                """INSERT INTO articles (search_id, title, url, published_date, source, state, gender, crime_type, sentence_details, snippet, source_type, defendant_name, victim_name, case_summary, quality_score, is_sentencing, ai_fingerprint)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    search_id,
                    a.get("title"),
                    a.get("url"),
                    a.get("published_date"),
                    a.get("source"),
                    a.get("state"),
                    a.get("gender"),
                    a.get("crime_type"),
                    a.get("sentence_details"),
                    a.get("snippet"),
                    a.get("source_type"),
                    a.get("defendant_name"),
                    a.get("victim_name"),
                    a.get("case_summary"),
                    a.get("quality_score"),
                    1 if a.get("is_sentencing") else 0,
                    a.get("ai_fingerprint"),
                ),
            )
        await db.commit()
    finally:
        await db.close()


async def get_articles_by_search(search_id: int) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM articles WHERE search_id = ? ORDER BY published_date DESC", (search_id,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_latest_search_articles() -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM search_history ORDER BY executed_at DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        if not row:
            return []
        search_id = row[0]
        return await get_articles_by_search(search_id)
    finally:
        await db.close()


async def save_search_config(name: str, search_params: dict) -> int:
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO saved_searches (name, search_params) VALUES (?, ?)",
            (name, json.dumps(search_params)),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def get_saved_searches() -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM saved_searches ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def delete_saved_search(search_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM saved_searches WHERE id = ?", (search_id,))
        await db.commit()
    finally:
        await db.close()


# Google Sheets tracker functions

async def get_active_spreadsheet() -> dict | None:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM google_sheets_tracker WHERE is_active = 1 LIMIT 1"
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def create_spreadsheet_record(spreadsheet_id: str, spreadsheet_url: str) -> int:
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO google_sheets_tracker (spreadsheet_id, spreadsheet_url) VALUES (?, ?)",
            (spreadsheet_id, spreadsheet_url),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def update_spreadsheet_count(sheet_db_id: int, new_count: int):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE google_sheets_tracker SET article_count = ? WHERE id = ?",
            (new_count, sheet_db_id),
        )
        await db.commit()
    finally:
        await db.close()


async def get_all_articles(page: int = 1, per_page: int = 100, search: str = "") -> tuple[list[dict], int]:
    db = await get_db()
    try:
        offset = (page - 1) * per_page
        if search:
            like = f"%{search}%"
            cursor = await db.execute(
                "SELECT COUNT(*) FROM articles WHERE title LIKE ? OR source LIKE ? OR state LIKE ? OR crime_type LIKE ?",
                (like, like, like, like),
            )
            total = (await cursor.fetchone())[0]
            cursor = await db.execute(
                "SELECT * FROM articles WHERE title LIKE ? OR source LIKE ? OR state LIKE ? OR crime_type LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (like, like, like, like, per_page, offset),
            )
        else:
            cursor = await db.execute("SELECT COUNT(*) FROM articles")
            total = (await cursor.fetchone())[0]
            cursor = await db.execute(
                "SELECT * FROM articles ORDER BY id DESC LIMIT ? OFFSET ?",
                (per_page, offset),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows], total
    finally:
        await db.close()


async def update_article(article_id: int, fields: dict):
    db = await get_db()
    try:
        sets = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [article_id]
        await db.execute(f"UPDATE articles SET {sets} WHERE id = ?", values)
        await db.commit()
    finally:
        await db.close()


async def delete_article(article_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM articles WHERE id = ?", (article_id,))
        await db.commit()
    finally:
        await db.close()


async def delete_all_articles():
    db = await get_db()
    try:
        await db.execute("DELETE FROM articles")
        await db.commit()
    finally:
        await db.close()


async def add_article(data: dict) -> int:
    db = await get_db()
    try:
        cursor = await db.execute(
            """INSERT INTO articles (search_id, title, url, published_date, source, state, gender, crime_type, sentence_details, snippet, source_type, defendant_name, victim_name, case_summary, quality_score)
               VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data.get("title", ""),
                data.get("url", ""),
                data.get("published_date", ""),
                data.get("source", ""),
                data.get("state", ""),
                data.get("gender", ""),
                data.get("crime_type", ""),
                data.get("sentence_details", ""),
                data.get("snippet", ""),
                data.get("source_type", ""),
                data.get("defendant_name", ""),
                data.get("victim_name", ""),
                data.get("case_summary", ""),
                data.get("quality_score"),
            ),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def get_existing_fingerprints() -> list[dict]:
    """Get all AI fingerprints from existing articles for cross-search dedup."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, defendant_name, victim_name, crime_type, state, sentence_details, ai_fingerprint FROM articles WHERE defendant_name IS NOT NULL AND defendant_name != ''"
        )
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            row = dict(r)
            # Try to parse the full fingerprint JSON
            if row.get("ai_fingerprint"):
                try:
                    fp = json.loads(row["ai_fingerprint"])
                    fp["_article_id"] = row["id"]
                    results.append(fp)
                    continue
                except (ValueError, TypeError):
                    pass
            # Fallback to individual columns
            results.append({
                "defendant_name": row.get("defendant_name"),
                "victim_name": row.get("victim_name"),
                "crime_type": row.get("crime_type"),
                "location_state": row.get("state"),
                "sentence": row.get("sentence_details"),
                "_article_id": row["id"],
            })
        return results
    finally:
        await db.close()


async def deactivate_spreadsheet(sheet_db_id: int):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE google_sheets_tracker SET is_active = 0, filled_at = CURRENT_TIMESTAMP WHERE id = ?",
            (sheet_db_id,),
        )
        await db.commit()
    finally:
        await db.close()
