import asyncio
import logging
from collections import Counter
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

from app.models import SearchRequest, SearchResponse, ArticleResult
from app.services.query_builder import build_query, build_query_for_source, get_query_variation
from app.services import news_fetcher
from app.services.nlp_extractor import analyze_article
from app.services.dedup import deduplicate_results, get_existing_urls, deduplicate_with_fingerprints
from app.database import save_search_history, save_articles, get_existing_fingerprints
from app.services.date_utils import parse_published_date
from app.config import settings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

MAX_ROUNDS = 10


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@router.post("/api/search", response_model=SearchResponse)
async def search_articles(req: SearchRequest):
    target = min(req.target_count, 200)
    all_results: list[dict] = []
    all_queries_used: list[str] = []
    total_ai_filtered = 0
    total_dupes = 0
    ai_analyzed = False
    seen_urls_session: set[str] = set()  # Track URLs within this entire search session

    logger.info(f"Target: {target} cases, deep_research={req.deep_research}")

    for round_num in range(MAX_ROUNDS):
        if len(all_results) >= target:
            break

        # Build query for this round
        if round_num == 0:
            query = build_query(
                crime_toggle=req.crime_toggle.value,
                state=req.state,
                gender=req.gender.value if req.gender else None,
                custom_keywords=req.custom_keywords,
            )
        else:
            query = get_query_variation(
                round_num - 1,
                crime_toggle=req.crime_toggle.value,
                state=req.state,
                gender=req.gender.value if req.gender else None,
                custom_keywords=req.custom_keywords,
            )
            if not query:
                logger.info(f"Round {round_num + 1}: no more query variations, stopping")
                break

        all_queries_used.append(query)
        logger.info(f"Round {round_num + 1}/{MAX_ROUNDS}: query='{query[:80]}...' (have {len(all_results)}/{target})")

        # === Fetch ===
        raw_articles = await _fetch_round(req, query)
        if not raw_articles:
            logger.info(f"Round {round_num + 1}: no articles returned")
            continue

        logger.info(f"Round {round_num + 1}: fetched {len(raw_articles)} raw articles")

        # === AI Analysis ===
        enriched, round_ai_filtered = await _analyze_round(raw_articles)
        total_ai_filtered += round_ai_filtered
        if enriched and any(a.get("quality_score") is not None for a in enriched):
            ai_analyzed = True

        # === Post-fetch filters ===
        filtered = _apply_filters(enriched, req)

        # === Dedup against DB + session ===
        existing_urls = await get_existing_urls()
        combined_urls = existing_urls | seen_urls_session
        deduped, url_dupes = deduplicate_results(filtered, combined_urls)
        total_dupes += url_dupes

        # Fingerprint dedup
        if ai_analyzed and deduped:
            try:
                existing_fps = await get_existing_fingerprints()
                # Also include already-accepted results as fingerprints
                session_fps = [_extract_fp_from_dict(r) for r in all_results if r.get("defendant_name")]
                all_fps = existing_fps + session_fps
                deduped, fp_dupes = deduplicate_with_fingerprints(deduped, all_fps)
                total_dupes += fp_dupes
            except Exception as e:
                logger.warning(f"Fingerprint dedup failed: {e}")

        # Track new URLs
        from app.services.dedup import normalize_url
        for article in deduped:
            seen_urls_session.add(normalize_url(article.get("url", "")))

        all_results.extend(deduped)
        logger.info(f"Round {round_num + 1}: +{len(deduped)} new cases (total: {len(all_results)}/{target})")

    # Trim to target
    all_results = all_results[:target]

    # Convert to ArticleResult
    results = [ArticleResult(**_to_article_dict(r)) for r in all_results]

    # Source breakdown
    source_breakdown = dict(Counter(r.source_type or "unknown" for r in results))

    # Save
    combined_query = " | ".join(all_queries_used[:3])
    if len(all_queries_used) > 3:
        combined_query += f" (+{len(all_queries_used) - 3} more)"
    search_params = req.model_dump(mode="json")
    search_id = await save_search_history(search_params, combined_query, len(results))
    await save_articles(search_id, [r.model_dump() for r in results])

    # Sheets
    sheets_url = None
    if settings.google_sheets_enabled:
        try:
            from app.services.sheets_exporter import push_articles_to_sheets
            sheets_url = await push_articles_to_sheets([r.model_dump() for r in results])
        except Exception as e:
            logger.warning(f"Google Sheets push failed: {e}")

    return SearchResponse(
        results=results,
        total_count=len(results),
        query_used=combined_query,
        duplicates_filtered=total_dupes,
        sheets_url=sheets_url,
        source_breakdown=source_breakdown if req.deep_research else None,
        ai_filtered=total_ai_filtered,
        ai_analyzed=ai_analyzed,
    )


async def _fetch_round(req: SearchRequest, query: str) -> list[dict]:
    """Fetch articles for one round."""
    if req.deep_research:
        query_yt = build_query_for_source(
            "youtube", req.crime_toggle.value, req.state,
            req.gender.value if req.gender else None, req.custom_keywords,
        )
        query_fb = build_query_for_source(
            "facebook", req.crime_toggle.value, req.state,
            req.gender.value if req.gender else None, req.custom_keywords,
        )

        search_tasks = await asyncio.gather(
            news_fetcher.search_serpapi(
                query=query, start_date=req.date_from,
                end_date=req.date_to, max_results=settings.gnews_max_results,
            ),
            news_fetcher.search_serpapi_web(
                query=query, start_date=req.date_from,
                end_date=req.date_to, max_results=20,
            ),
            news_fetcher.search_serpapi_facebook(
                query=query_fb, start_date=req.date_from,
                end_date=req.date_to, max_results=10,
            ),
            news_fetcher.search_serpapi_youtube(
                query=query_yt, start_date=req.date_from,
                end_date=req.date_to, max_results=15,
            ),
            return_exceptions=True,
        )

        raw_articles = []
        source_names = ["google_news", "google_web", "facebook", "youtube"]
        for i, result in enumerate(search_tasks):
            if isinstance(result, Exception):
                logger.warning(f"{source_names[i]} search failed: {result}")
                continue
            raw_articles.extend(result)
        return raw_articles
    else:
        try:
            return await news_fetcher.search_serpapi(
                query=query, start_date=req.date_from,
                end_date=req.date_to, max_results=settings.gnews_max_results,
            )
        except Exception as e:
            logger.warning(f"SerpAPI failed ({e}), falling back to RSS")
            return await news_fetcher.search_rss(
                query=query, start_date=req.date_from, end_date=req.date_to,
            )


async def _analyze_round(raw_articles: list[dict]) -> tuple[list[dict], int]:
    """AI-analyze a round of articles. Returns (enriched_articles, ai_filtered_count)."""
    if not raw_articles:
        return [], 0

    if settings.ai_analysis_enabled and settings.anthropic_api_key:
        try:
            from app.services.ai_analyzer import analyze_batch
            enriched = await analyze_batch(raw_articles)
            pre_count = len(enriched)
            enriched = [
                a for a in enriched
                if a.get("is_sentencing", True)
                and (a.get("quality_score", 100) >= settings.ai_quality_threshold)
            ]
            return enriched, pre_count - len(enriched)
        except Exception as e:
            logger.error(f"AI analysis failed: {e}")

    return _regex_fallback(raw_articles), 0


def _apply_filters(articles: list[dict], req: SearchRequest) -> list[dict]:
    """Apply state/gender/date post-fetch filters."""
    filtered = []
    for raw in articles:
        # Date filter — the critical safety net
        if req.date_from or req.date_to:
            parsed_date = parse_published_date(raw.get("published_date", ""))
            if parsed_date is None:
                continue  # Reject unparseable dates when a date range is set
            if req.date_from and parsed_date < req.date_from:
                continue
            if req.date_to and parsed_date > req.date_to:
                continue

        # State filter
        article_state = raw.get("state") or raw.get("location_state")
        if req.state and req.state.lower() != "any":
            if article_state and article_state.lower() != req.state.lower():
                continue

        # Gender filter
        article_gender = raw.get("gender")
        if req.gender and req.gender.value != "any":
            if article_gender and article_gender.lower() != req.gender.value.lower():
                continue

        raw["state"] = article_state
        filtered.append(raw)
    return filtered


def _to_article_dict(raw: dict) -> dict:
    """Normalize a raw article dict for ArticleResult construction."""
    return {
        "title": raw.get("title", ""),
        "url": raw.get("url", ""),
        "published_date": raw.get("published_date", ""),
        "source": raw.get("source", ""),
        "state": raw.get("state"),
        "gender": raw.get("gender"),
        "crime_type": raw.get("crime_type"),
        "sentence_details": raw.get("sentence_details"),
        "snippet": raw.get("snippet", ""),
        "source_type": raw.get("source_type"),
        "defendant_name": raw.get("defendant_name"),
        "victim_name": raw.get("victim_name"),
        "case_summary": raw.get("case_summary"),
        "quality_score": raw.get("quality_score"),
        "is_sentencing": raw.get("is_sentencing"),
    }


def _extract_fp_from_dict(article: dict) -> dict:
    """Extract fingerprint from an article dict for dedup comparison."""
    return {
        "defendant_name": article.get("defendant_name"),
        "victim_name": article.get("victim_name"),
        "crime_type": article.get("crime_type"),
        "location_state": article.get("state"),
        "sentence": article.get("sentence_details"),
    }


def _regex_fallback(raw_articles: list[dict]) -> list[dict]:
    """Fall back to regex-based NLP when AI is unavailable."""
    enriched = []
    for raw in raw_articles:
        text = raw.get("snippet", "")
        analysis = analyze_article(raw.get("title", ""), text)
        raw["state"] = raw.get("state") or analysis.get("state")
        raw["gender"] = raw.get("gender") or analysis.get("gender")
        raw["crime_type"] = raw.get("crime_type") or analysis.get("crime_type")
        raw["sentence_details"] = raw.get("sentence_details") or analysis.get("sentence_details")
        raw["quality_score"] = None
        raw["is_sentencing"] = True
        raw["defendant_name"] = None
        raw["victim_name"] = None
        raw["case_summary"] = None
        enriched.append(raw)
    return enriched
