import difflib
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import aiosqlite
from app.config import settings

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "source", "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid",
}


def normalize_url(url: str) -> str:
    """Normalize a URL for deduplication."""
    if not url:
        return ""

    parsed = urlparse(url.lower())

    # Strip www prefix
    host = parsed.netloc
    if host.startswith("www."):
        host = host[4:]

    # Remove tracking params
    params = parse_qs(parsed.query, keep_blank_values=False)
    filtered = {k: v for k, v in params.items() if k.lower() not in TRACKING_PARAMS}
    clean_query = urlencode(filtered, doseq=True)

    # Strip trailing slash
    path = parsed.path.rstrip("/")

    return f"{host}{path}{'?' + clean_query if clean_query else ''}"


def title_similarity(a: str, b: str) -> float:
    """Compute similarity between two article titles."""
    if not a or not b:
        return 0.0

    # Normalize: lowercase, strip punctuation, collapse whitespace
    def clean(s):
        s = s.lower()
        s = re.sub(r"[^\w\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    return difflib.SequenceMatcher(None, clean(a), clean(b)).ratio()


async def get_existing_urls() -> set[str]:
    """Get all normalized URLs already in the database."""
    db = await aiosqlite.connect(settings.database_url)
    try:
        cursor = await db.execute("SELECT DISTINCT url FROM articles")
        rows = await cursor.fetchall()
        return {normalize_url(row[0]) for row in rows if row[0]}
    finally:
        await db.close()


def deduplicate_results(articles: list[dict], existing_urls: set[str]) -> tuple[list[dict], int]:
    """Remove duplicates from results. Returns (filtered_articles, duplicate_count)."""
    seen_urls = set()
    filtered = []
    dupe_count = 0

    for article in articles:
        norm_url = normalize_url(article.get("url", ""))

        # Check against DB
        if norm_url in existing_urls:
            dupe_count += 1
            continue

        # Check within current batch (by URL)
        if norm_url in seen_urls:
            dupe_count += 1
            continue

        # Check within current batch (by title similarity)
        is_title_dupe = False
        for existing in filtered:
            if title_similarity(article.get("title", ""), existing.get("title", "")) > 0.85:
                is_title_dupe = True
                dupe_count += 1
                break

        if is_title_dupe:
            continue

        seen_urls.add(norm_url)
        filtered.append(article)

    return filtered, dupe_count


def _clean_name(name: str) -> str:
    """Normalize a person's name for comparison."""
    if not name:
        return ""
    return re.sub(r"[^\w\s]", "", name.lower()).strip()


def _name_match(a: str, b: str) -> bool:
    """Fuzzy match two person names."""
    ca, cb = _clean_name(a), _clean_name(b)
    if not ca or not cb:
        return False
    # Exact match
    if ca == cb:
        return True
    # Fuzzy match
    if difflib.SequenceMatcher(None, ca, cb).ratio() > 0.8:
        return True
    # First + last name in either order
    parts_a = ca.split()
    parts_b = cb.split()
    if len(parts_a) >= 2 and len(parts_b) >= 2:
        # Check if first and last names match in any order
        if parts_a[0] == parts_b[0] and parts_a[-1] == parts_b[-1]:
            return True
        if parts_a[0] == parts_b[-1] and parts_a[-1] == parts_b[0]:
            return True
    return False


def fingerprint_match(fp1: dict, fp2: dict) -> bool:
    """Check if two case fingerprints represent the same case."""
    name1 = fp1.get("defendant_name")
    name2 = fp2.get("defendant_name")

    # Cannot match without defendant names
    if not name1 or not name2:
        return False

    if not _name_match(name1, name2):
        return False

    # Name matches — check supporting evidence
    # Same state
    state1 = (fp1.get("location_state") or "").lower().strip()
    state2 = (fp2.get("location_state") or "").lower().strip()
    if state1 and state2 and state1 == state2:
        return True

    # Same crime type
    crime1 = (fp1.get("crime_type") or "").lower().strip()
    crime2 = (fp2.get("crime_type") or "").lower().strip()
    if crime1 and crime2 and (crime1 in crime2 or crime2 in crime1):
        return True

    # Same victim
    victim1 = fp1.get("victim_name")
    victim2 = fp2.get("victim_name")
    if victim1 and victim2 and _name_match(victim1, victim2):
        return True

    # Same sentence
    sent1 = (fp1.get("sentence") or fp1.get("sentence_details") or "").lower().strip()
    sent2 = (fp2.get("sentence") or fp2.get("sentence_details") or "").lower().strip()
    if sent1 and sent2 and difflib.SequenceMatcher(None, sent1, sent2).ratio() > 0.7:
        return True

    # Name match alone with no other confirming data — still likely same person
    # but be conservative, don't match
    return False


def deduplicate_with_fingerprints(
    articles: list[dict], existing_fingerprints: list[dict]
) -> tuple[list[dict], int]:
    """Second-pass dedup using AI case fingerprints. Cross-source aware."""
    filtered = []
    dupe_count = 0

    for article in articles:
        fp = _extract_fp(article)
        is_dupe = False

        # Check against DB fingerprints
        for existing_fp in existing_fingerprints:
            if fingerprint_match(fp, existing_fp):
                is_dupe = True
                break

        # Check against already-accepted articles in this batch
        if not is_dupe:
            for accepted in filtered:
                if fingerprint_match(fp, _extract_fp(accepted)):
                    is_dupe = True
                    break

        if is_dupe:
            dupe_count += 1
        else:
            filtered.append(article)

    return filtered, dupe_count


def _extract_fp(article: dict) -> dict:
    """Extract fingerprint fields from an article dict."""
    # Handle both raw fingerprint dicts and article dicts with nested data
    import json as _json
    fp_str = article.get("ai_fingerprint")
    if fp_str and isinstance(fp_str, str):
        try:
            return _json.loads(fp_str)
        except (ValueError, TypeError):
            pass
    return {
        "defendant_name": article.get("defendant_name"),
        "victim_name": article.get("victim_name"),
        "crime_type": article.get("crime_type"),
        "location_state": article.get("location_state") or article.get("state"),
        "sentence": article.get("sentence") or article.get("sentence_details"),
    }
