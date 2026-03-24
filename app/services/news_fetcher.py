import asyncio
import logging
from datetime import date, datetime
from typing import Optional

import feedparser
import httpx

from app.config import settings
from app.services.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)
_limiter = RateLimiter(delay_seconds=settings.request_delay_seconds)


def _build_tbs(start_date: Optional[date], end_date: Optional[date]) -> Optional[str]:
    """Build tbs date range param for Google engine."""
    if start_date and end_date:
        return f"cdr:1,cd_min:{start_date.strftime('%m/%d/%Y')},cd_max:{end_date.strftime('%m/%d/%Y')}"
    elif start_date:
        return f"cdr:1,cd_min:{start_date.strftime('%m/%d/%Y')},cd_max:{datetime.now().strftime('%m/%d/%Y')}"
    return None


def _youtube_sp_param(start_date: Optional[date], end_date: Optional[date]) -> Optional[str]:
    """Pick the tightest YouTube upload date filter for the given range."""
    if not start_date:
        return None
    today = date.today()
    days_back = (today - start_date).days
    if days_back <= 1:
        return "EgIIAg%3D%3D"   # Today
    elif days_back <= 7:
        return "EgIIAw%3D%3D"   # This week
    elif days_back <= 31:
        return "EgIIBA%3D%3D"   # This month
    elif days_back <= 365:
        return "EgIIBQ%3D%3D"   # This year
    return None


async def search_serpapi(
    query: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    max_results: int = 50,
) -> list[dict]:
    """Search Google News using SerpAPI with reliable tbs date filtering."""
    from serpapi import GoogleSearch

    params = {
        "engine": "google",
        "q": query,
        "tbm": "nws",
        "api_key": settings.serpapi_key,
        "gl": "us",
        "hl": "en",
        "num": min(max_results, 100),
    }

    tbs = _build_tbs(start_date, end_date)
    if tbs:
        params["tbs"] = tbs

    def _fetch():
        search = GoogleSearch(params)
        results = search.get_dict()
        articles = []
        # tbm=nws returns results under "news_results"
        for item in results.get("news_results", []):
            articles.append(_parse_serpapi_result(item, "google_news"))
            if len(articles) >= max_results:
                break
        return articles[:max_results]

    return await asyncio.to_thread(_fetch)


async def search_serpapi_web(
    query: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    max_results: int = 20,
) -> list[dict]:
    """Search Google Web for broader article coverage."""
    from serpapi import GoogleSearch

    params = {
        "engine": "google",
        "q": query,
        "api_key": settings.serpapi_key,
        "gl": "us",
        "hl": "en",
        "num": max_results,
    }

    tbs = _build_tbs(start_date, end_date)
    if tbs:
        params["tbs"] = tbs

    def _fetch():
        search = GoogleSearch(params)
        results = search.get_dict()
        articles = []
        for item in results.get("organic_results", []):
            articles.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "published_date": item.get("date", ""),
                "source": item.get("source", item.get("displayed_link", "")),
                "snippet": item.get("snippet", ""),
                "source_type": "google_web",
            })
        return articles[:max_results]

    return await asyncio.to_thread(_fetch)


async def search_serpapi_facebook(
    query: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    max_results: int = 10,
) -> list[dict]:
    """Search Facebook pages via Google site search."""
    from serpapi import GoogleSearch

    fb_query = f'site:facebook.com {query} ("police department" OR "news" OR "sheriff")'

    params = {
        "engine": "google",
        "q": fb_query,
        "api_key": settings.serpapi_key,
        "gl": "us",
        "hl": "en",
        "num": max_results,
    }

    tbs = _build_tbs(start_date, end_date)
    if tbs:
        params["tbs"] = tbs

    def _fetch():
        search = GoogleSearch(params)
        results = search.get_dict()
        articles = []
        for item in results.get("organic_results", []):
            articles.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "published_date": item.get("date", ""),
                "source": item.get("source", "Facebook"),
                "snippet": item.get("snippet", ""),
                "source_type": "facebook",
            })
        return articles[:max_results]

    return await asyncio.to_thread(_fetch)


async def search_serpapi_youtube(
    query: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    max_results: int = 15,
) -> list[dict]:
    """Search YouTube for video news coverage of sentencing cases."""
    from serpapi import GoogleSearch

    params = {
        "engine": "youtube",
        "search_query": query,
        "api_key": settings.serpapi_key,
    }

    sp = _youtube_sp_param(start_date, end_date)
    if sp:
        params["sp"] = sp

    def _fetch():
        search = GoogleSearch(params)
        results = search.get_dict()
        articles = []
        for item in results.get("video_results", []):
            channel = item.get("channel", {})
            channel_name = channel.get("name", "") if isinstance(channel, dict) else str(channel)
            articles.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "published_date": item.get("published_date", ""),
                "source": channel_name,
                "snippet": item.get("description", item.get("title", "")),
                "source_type": "youtube",
            })
            if len(articles) >= max_results:
                break
        return articles[:max_results]

    return await asyncio.to_thread(_fetch)


def _parse_serpapi_result(item: dict, source_type: str = "google_news") -> dict:
    """Parse a single SerpAPI news result into our standard format."""
    source = ""
    if isinstance(item.get("source"), dict):
        source = item["source"].get("name", "")
    elif isinstance(item.get("source"), str):
        source = item["source"]

    return {
        "title": item.get("title", ""),
        "url": item.get("link", ""),
        "published_date": item.get("date", ""),
        "source": source,
        "snippet": item.get("snippet", item.get("title", "")),
        "source_type": source_type,
    }


async def search_rss(
    query: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[dict]:
    """Fallback: search Google News via RSS feed."""
    import urllib.parse

    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"

    await _limiter.acquire()

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    feed = feedparser.parse(resp.text)
    articles = []

    for entry in feed.entries:
        pub_date = entry.get("published", "")
        if pub_date and (start_date or end_date):
            try:
                from email.utils import parsedate_to_datetime
                entry_dt = parsedate_to_datetime(pub_date).date()
                if start_date and entry_dt < start_date:
                    continue
                if end_date and entry_dt > end_date:
                    continue
            except (ValueError, TypeError):
                pass

        source = ""
        if hasattr(entry, "source") and hasattr(entry.source, "title"):
            source = entry.source.title
        elif " - " in entry.get("title", ""):
            parts = entry["title"].rsplit(" - ", 1)
            if len(parts) == 2:
                source = parts[1]

        articles.append({
            "title": entry.get("title", ""),
            "url": entry.get("link", ""),
            "published_date": pub_date,
            "source": source,
            "snippet": entry.get("summary", ""),
            "source_type": "rss",
        })

    return articles


async def fetch_article_text(url: str) -> Optional[str]:
    """Fetch full article text from a URL."""
    try:
        await _limiter.acquire()
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Tripoli/1.0)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()

        article = (
            soup.find("article")
            or soup.find("div", class_="article-body")
            or soup.find("div", class_="story-body")
            or soup.find("main")
        )

        if article:
            text = article.get_text(separator=" ", strip=True)
        else:
            paragraphs = soup.find_all("p")
            text = " ".join(p.get_text(strip=True) for p in paragraphs)

        return text[:10000] if text else None

    except Exception:
        return None
