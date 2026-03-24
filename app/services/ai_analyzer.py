import asyncio
import json
import logging
from typing import Optional

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)

_client: Optional[anthropic.AsyncAnthropic] = None

SYSTEM_PROMPT = """You are analyzing news articles/posts to determine if they are about a criminal court sentencing. Extract structured information from the title and content provided.

Be precise about names and locations. If information is not clearly stated, use null.

For YouTube videos, you only have the title and description — be stricter about quality_score since less context is available.
For Facebook posts, content may be fragmentary — extract what you can.

quality_score guidelines:
- 80-100: Clearly about a specific court sentencing with defendant name and details
- 60-79: About sentencing but some details missing or unclear
- 40-59: Mentions sentencing but may be tangential or about charges only (not yet sentenced)
- 20-39: Marginally related — mentions crime but no sentencing
- 0-19: Not about sentencing at all

Respond with ONLY valid JSON matching this exact structure (no markdown, no extra text):
{
  "defendant_name": "string or null",
  "victim_name": "string or null",
  "crime_type": "string or null (e.g. Murder, Sexual Assault, Shooting, Robbery, Assault, DUI, Child Abuse)",
  "location_city": "string or null",
  "location_state": "string or null (full US state name)",
  "sentence": "string or null (e.g. '25 years in prison', 'life without parole')",
  "court": "string or null",
  "is_sentencing_article": true or false,
  "quality_score": 0-100,
  "gender": "Male or Female or null (of the defendant)",
  "case_summary": "1-2 sentence summary of the case or null"
}"""


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def analyze_article_ai(title: str, snippet: str, source_type: str = "google_news") -> dict:
    """Analyze a single article with Claude AI. Returns a case fingerprint dict."""
    try:
        client = _get_client()
        user_msg = f"Source type: {source_type}\nTitle: {title}\nContent: {snippet or title}"

        response = await client.messages.create(
            model=settings.ai_model,
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": "{"},
            ],
        )

        text = "{" + response.content[0].text.strip()
        # Try to extract JSON from response
        fingerprint = _parse_json_response(text)
        if fingerprint is None:
            logger.warning(f"AI returned unparseable response for '{title[:50]}'")
            return _fallback_fingerprint()
        return fingerprint

    except json.JSONDecodeError as e:
        logger.warning(f"AI returned invalid JSON for '{title[:50]}': {e}")
        return _fallback_fingerprint()
    except Exception as e:
        logger.warning(f"AI analysis failed for '{title[:50]}': {e}")
        return _fallback_fingerprint()


def _parse_json_response(text: str) -> dict | None:
    """Try to parse JSON from AI response, handling various formats."""
    import re
    # Direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    # Try to find JSON object in response
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _fallback_fingerprint() -> dict:
    """Return a safe fallback when AI analysis fails."""
    return {
        "defendant_name": None,
        "victim_name": None,
        "crime_type": None,
        "location_city": None,
        "location_state": None,
        "sentence": None,
        "court": None,
        "is_sentencing_article": True,
        "quality_score": 50,
        "gender": None,
        "case_summary": None,
    }


async def analyze_batch(articles: list[dict], max_concurrent: int = 10) -> list[dict]:
    """Analyze a batch of articles with AI, enriching each with fingerprint data."""
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _analyze_one(article: dict) -> dict:
        async with semaphore:
            fingerprint = await analyze_article_ai(
                title=article.get("title", ""),
                snippet=article.get("snippet", ""),
                source_type=article.get("source_type", "google_news"),
            )
            # Merge fingerprint into article
            article["defendant_name"] = fingerprint.get("defendant_name")
            article["victim_name"] = fingerprint.get("victim_name")
            article["crime_type"] = fingerprint.get("crime_type")
            article["location_state"] = fingerprint.get("location_state")
            article["location_city"] = fingerprint.get("location_city")
            article["sentence"] = fingerprint.get("sentence")
            article["court"] = fingerprint.get("court")
            article["is_sentencing"] = fingerprint.get("is_sentencing_article", True)
            article["quality_score"] = fingerprint.get("quality_score", 50)
            article["gender"] = fingerprint.get("gender")
            article["case_summary"] = fingerprint.get("case_summary")
            article["ai_fingerprint"] = json.dumps(fingerprint)
            # Use AI-extracted state if available
            if fingerprint.get("location_state"):
                article["state"] = fingerprint["location_state"]
            # Use AI sentence details
            if fingerprint.get("sentence"):
                article["sentence_details"] = fingerprint["sentence"]
            return article

    tasks = [_analyze_one(article) for article in articles]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    enriched = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning(f"Batch analysis failed for article {i}: {result}")
            articles[i].update(_fallback_fingerprint())
            articles[i]["ai_fingerprint"] = None
            enriched.append(articles[i])
        else:
            enriched.append(result)

    return enriched
