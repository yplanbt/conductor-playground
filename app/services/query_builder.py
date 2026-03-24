import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def load_keywords() -> dict:
    with open(DATA_DIR / "keywords.json") as f:
        return json.load(f)


def build_query(
    crime_toggle: str = "both",
    state: str | None = None,
    gender: str | None = None,
    custom_keywords: list[str] | None = None,
) -> str:
    """Build a concise search query optimized for SerpAPI Google News."""
    parts = ["sentenced"]

    if crime_toggle == "death":
        parts.append("murder OR killed OR homicide")
    elif crime_toggle == "serious":
        parts.append("shooting OR rape OR assault OR robbery")
    elif crime_toggle == "both":
        parts.append("murder OR shooting OR rape OR killed")

    if state and state.lower() != "any":
        parts.append(f'"{state}"')

    if gender and gender.lower() not in ("any", ""):
        if gender.lower() == "male":
            parts.append("man OR he")
        elif gender.lower() == "female":
            parts.append("woman OR she")

    if custom_keywords:
        filtered = [k.strip() for k in custom_keywords if k.strip()]
        if filtered:
            parts.append(" OR ".join(filtered))

    return " ".join(parts)


def build_query_for_source(
    source_type: str,
    crime_toggle: str = "both",
    state: str | None = None,
    gender: str | None = None,
    custom_keywords: list[str] | None = None,
) -> str:
    """Build a query variant optimized for a specific source type."""
    if source_type == "youtube":
        # YouTube: simpler query, drop gender (less useful for video titles)
        parts = ["sentenced"]
        if crime_toggle == "death":
            parts.append("murder OR killed")
        elif crime_toggle == "serious":
            parts.append("shooting OR rape OR assault")
        elif crime_toggle == "both":
            parts.append("murder OR shooting OR crime")
        if state and state.lower() != "any":
            parts.append(state)
        if custom_keywords:
            filtered = [k.strip() for k in custom_keywords if k.strip()]
            if filtered:
                parts.append(" ".join(filtered[:3]))  # Limit to 3 for YouTube
        return " ".join(parts)

    if source_type == "facebook":
        # Facebook: the site: prefix is added by the fetcher, keep query focused
        parts = ["sentenced"]
        if crime_toggle == "death":
            parts.append("murder OR killed OR homicide")
        elif crime_toggle == "serious":
            parts.append("shooting OR rape OR assault")
        elif crime_toggle == "both":
            parts.append("murder OR shooting OR crime")
        if state and state.lower() != "any":
            parts.append(f'"{state}"')
        if custom_keywords:
            filtered = [k.strip() for k in custom_keywords if k.strip()]
            if filtered:
                parts.append(" OR ".join(filtered))
        return " ".join(parts)

    # Default: google_web and google_news use the standard query
    return build_query(crime_toggle, state, gender, custom_keywords)


# Query variations for multi-round searching
QUERY_VARIATIONS = {
    "death": [
        ["sentenced", "murder"],
        ["convicted", "homicide"],
        ["sentenced", "killed", "prison"],
        ["guilty", "murder", "sentenced"],
        ["sentenced", "death", "shooting"],
        ["prison", "manslaughter", "sentenced"],
        ["convicted", "killing", "sentenced"],
        ["life sentence", "murder"],
        ["death penalty", "convicted"],
        ["years prison", "murder", "sentenced"],
    ],
    "serious": [
        ["sentenced", "shooting"],
        ["convicted", "rape"],
        ["sentenced", "assault", "prison"],
        ["guilty", "robbery", "sentenced"],
        ["sentenced", "sexual assault"],
        ["convicted", "armed robbery"],
        ["sentenced", "child abuse"],
        ["prison", "aggravated assault"],
        ["sentenced", "kidnapping"],
        ["convicted", "arson", "sentenced"],
    ],
    "both": [
        ["sentenced", "murder OR shooting"],
        ["convicted", "homicide OR rape"],
        ["sentenced", "prison", "killed OR assault"],
        ["guilty", "murder OR robbery"],
        ["sentenced", "crime", "prison"],
        ["convicted", "sentenced", "years"],
        ["life sentence", "murder OR assault"],
        ["sentenced", "death OR shooting OR rape"],
        ["prison sentence", "convicted", "crime"],
        ["guilty verdict", "sentenced"],
    ],
}


def get_query_variation(
    round_num: int,
    crime_toggle: str = "both",
    state: str | None = None,
    gender: str | None = None,
    custom_keywords: list[str] | None = None,
) -> str | None:
    """Get a query variation for a specific round. Returns None if no more variations."""
    variations = QUERY_VARIATIONS.get(crime_toggle, QUERY_VARIATIONS["both"])

    if round_num >= len(variations):
        return None

    parts = list(variations[round_num])

    if state and state.lower() != "any":
        parts.append(f'"{state}"')

    if gender and gender.lower() not in ("any", ""):
        if gender.lower() == "male":
            parts.append("man")
        elif gender.lower() == "female":
            parts.append("woman")

    if custom_keywords:
        filtered = [k.strip() for k in custom_keywords if k.strip()]
        if filtered:
            parts.append(" OR ".join(filtered[:2]))

    return " ".join(parts)
