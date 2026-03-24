import asyncio
import logging
from datetime import datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from app.config import settings
from app.database import (
    get_active_spreadsheet,
    create_spreadsheet_record,
    update_spreadsheet_count,
    deactivate_spreadsheet,
)

logger = logging.getLogger(__name__)

_client: Optional[gspread.Client] = None

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

HEADER_ROW = [
    "Title", "URL", "Published Date", "Source",
    "State", "Gender", "Crime Type", "Sentence Details", "Snippet",
]


def _get_client() -> gspread.Client:
    global _client
    if _client is None:
        creds = Credentials.from_service_account_file(
            settings.google_service_account_file, scopes=SCOPES
        )
        _client = gspread.authorize(creds)
    return _client


def _create_spreadsheet(client: gspread.Client) -> tuple[str, str]:
    """Create a new spreadsheet and return (spreadsheet_id, url)."""
    title = f"Tripoli Articles - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    spreadsheet = client.create(title)

    # Write header row
    worksheet = spreadsheet.sheet1
    worksheet.append_row(HEADER_ROW)

    # Share with user if email configured
    if settings.google_sheets_share_email:
        spreadsheet.share(
            settings.google_sheets_share_email,
            perm_type="user",
            role="writer",
        )

    return spreadsheet.id, spreadsheet.url


def _article_to_row(article: dict) -> list[str]:
    return [
        article.get("title", ""),
        article.get("url", ""),
        article.get("published_date", ""),
        article.get("source", ""),
        article.get("state", ""),
        article.get("gender", ""),
        article.get("crime_type", ""),
        article.get("sentence_details", ""),
        article.get("snippet", ""),
    ]


async def push_articles_to_sheets(articles: list[dict]) -> Optional[str]:
    """Push articles to Google Sheets. Returns the active spreadsheet URL."""
    if not articles:
        return None

    def _sync_push():
        client = _get_client()
        remaining = list(articles)
        active_url = None

        while remaining:
            # Get or create active spreadsheet
            active = None

            # We need to use sync DB calls here since we're in a thread
            # Instead, we'll handle this via the async wrapper
            return remaining, client

        return [], client

    def _do_push(remaining_articles, active_sheet_info, client):
        """Synchronous push to sheets."""
        spreadsheet_id = active_sheet_info["spreadsheet_id"]
        current_count = active_sheet_info["article_count"]
        max_articles = settings.google_sheets_max_articles

        capacity = max_articles - current_count
        batch = remaining_articles[:capacity]
        overflow = remaining_articles[capacity:]

        if batch:
            spreadsheet = client.open_by_key(spreadsheet_id)
            worksheet = spreadsheet.sheet1
            rows = [_article_to_row(a) for a in batch]
            worksheet.append_rows(rows)

        return len(batch), overflow, active_sheet_info

    try:
        client = await asyncio.to_thread(_get_client)
        remaining = list(articles)
        active_url = None

        while remaining:
            # Get active spreadsheet from DB
            active = await get_active_spreadsheet()

            if not active:
                # Create new spreadsheet
                sid, url = await asyncio.to_thread(_create_spreadsheet, client)
                db_id = await create_spreadsheet_record(sid, url)
                active = {
                    "id": db_id,
                    "spreadsheet_id": sid,
                    "spreadsheet_url": url,
                    "article_count": 0,
                }

            active_url = active["spreadsheet_url"]
            capacity = settings.google_sheets_max_articles - active["article_count"]

            if capacity <= 0:
                # Sheet is full, deactivate and create new
                await deactivate_spreadsheet(active["id"])
                continue

            batch = remaining[:capacity]
            remaining = remaining[capacity:]

            # Push batch to sheets
            rows = [_article_to_row(a) for a in batch]

            def _append_rows(rows_to_add, sheet_id):
                spreadsheet = client.open_by_key(sheet_id)
                worksheet = spreadsheet.sheet1
                worksheet.append_rows(rows_to_add)

            await asyncio.to_thread(_append_rows, rows, active["spreadsheet_id"])

            # Update count
            new_count = active["article_count"] + len(batch)
            await update_spreadsheet_count(active["id"], new_count)

            if new_count >= settings.google_sheets_max_articles:
                await deactivate_spreadsheet(active["id"])

        return active_url

    except Exception as e:
        logger.error(f"Google Sheets push failed: {e}")
        return None
