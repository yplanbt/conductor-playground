from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional

from app.database import get_all_articles, update_article, delete_article, delete_all_articles, add_article

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/articles", response_class=HTMLResponse)
async def articles_page(request: Request):
    return templates.TemplateResponse(request, "articles.html")


@router.get("/api/articles")
async def list_articles(page: int = 1, per_page: int = 100, q: str = ""):
    articles, total = await get_all_articles(page=page, per_page=per_page, search=q)
    return {
        "articles": articles,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }


class ArticleUpdate(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None
    published_date: Optional[str] = None
    source: Optional[str] = None
    state: Optional[str] = None
    gender: Optional[str] = None
    crime_type: Optional[str] = None
    sentence_details: Optional[str] = None
    snippet: Optional[str] = None
    defendant_name: Optional[str] = None
    victim_name: Optional[str] = None
    case_summary: Optional[str] = None


class ArticleCreate(BaseModel):
    title: str
    url: str = ""
    published_date: str = ""
    source: str = ""
    state: str = ""
    gender: str = ""
    crime_type: str = ""
    sentence_details: str = ""
    snippet: str = ""
    defendant_name: str = ""
    victim_name: str = ""
    case_summary: str = ""


@router.delete("/api/articles")
async def remove_all_articles():
    await delete_all_articles()
    return {"ok": True}


@router.patch("/api/articles/{article_id}")
async def patch_article(article_id: int, update: ArticleUpdate):
    fields = {k: v for k, v in update.model_dump().items() if v is not None}
    if not fields:
        return {"ok": True}
    await update_article(article_id, fields)
    return {"ok": True}


@router.delete("/api/articles/{article_id}")
async def remove_article(article_id: int):
    await delete_article(article_id)
    return {"ok": True}


@router.post("/api/articles")
async def create_article(article: ArticleCreate):
    article_id = await add_article(article.model_dump())
    return {"ok": True, "id": article_id}
