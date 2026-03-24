import csv
import io

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.database import get_articles_by_search, get_latest_search_articles

router = APIRouter()


@router.get("/api/export/csv")
async def export_csv(search_id: int | None = None):
    if search_id:
        articles = await get_articles_by_search(search_id)
    else:
        articles = await get_latest_search_articles()

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "Title", "URL", "Published Date", "Source",
        "State", "Gender", "Crime Type", "Sentence Details", "Snippet"
    ])

    for a in articles:
        writer.writerow([
            a.get("title", ""),
            a.get("url", ""),
            a.get("published_date", ""),
            a.get("source", ""),
            a.get("state", ""),
            a.get("gender", ""),
            a.get("crime_type", ""),
            a.get("sentence_details", ""),
            a.get("snippet", ""),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sentencing_articles.csv"},
    )
