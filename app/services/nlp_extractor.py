import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

_states_data = None
_keywords_data = None


def _load_states():
    global _states_data
    if _states_data is None:
        with open(DATA_DIR / "us_states.json") as f:
            _states_data = json.load(f)
    return _states_data


def _load_keywords():
    global _keywords_data
    if _keywords_data is None:
        with open(DATA_DIR / "keywords.json") as f:
            _keywords_data = json.load(f)
    return _keywords_data


def extract_state(text: str) -> str | None:
    """Detect most mentioned US state from article text."""
    if not text:
        return None

    states = _load_states()["states"]
    text_lower = text.lower()
    scores: dict[str, int] = {}

    for s in states:
        name = s["name"]
        name_lower = name.lower()
        # Count state name mentions
        count = text_lower.count(name_lower)
        if count > 0:
            scores[name] = scores.get(name, 0) + count * 3

        # Count abbreviation mentions (surrounded by non-alpha chars)
        abbr_pattern = rf"\b{re.escape(s['abbr'])}\b"
        abbr_matches = len(re.findall(abbr_pattern, text))
        if abbr_matches:
            scores[name] = scores.get(name, 0) + abbr_matches * 2

        # Count city mentions
        for city in s.get("cities", []):
            city_count = text_lower.count(city.lower())
            if city_count > 0:
                scores[name] = scores.get(name, 0) + city_count

    if not scores:
        return None

    return max(scores, key=scores.get)


def extract_gender(text: str) -> str | None:
    """Detect gender of the primary subject (person sentenced)."""
    if not text:
        return None

    text_lower = text.lower()

    male_terms = ["he was", "his ", "him ", " man ", "male ", "father", "husband", "son ", "boy ", " he "]
    female_terms = ["she was", "her ", "hers ", " woman ", "female ", "mother", "wife", "daughter", "girl ", " she "]

    # Look for gendered terms near sentencing keywords
    sentencing_words = ["sentenced", "convicted", "guilty", "prison", "jail"]

    male_score = 0
    female_score = 0

    for sw in sentencing_words:
        idx = text_lower.find(sw)
        while idx != -1:
            window_start = max(0, idx - 200)
            window_end = min(len(text_lower), idx + 200)
            window = text_lower[window_start:window_end]

            for term in male_terms:
                male_score += window.count(term) * 2
            for term in female_terms:
                female_score += window.count(term) * 2

            idx = text_lower.find(sw, idx + 1)

    # Also count overall mentions with lower weight
    for term in male_terms:
        male_score += text_lower.count(term)
    for term in female_terms:
        female_score += text_lower.count(term)

    if male_score == 0 and female_score == 0:
        return None
    if male_score > female_score:
        return "Male"
    if female_score > male_score:
        return "Female"
    return None


def extract_crime_type(text: str) -> str | None:
    """Categorize the crime type from article text."""
    if not text:
        return None

    kw = _load_keywords()
    categories = kw.get("crime_categories", {})
    text_lower = text.lower()

    scores: dict[str, int] = {}
    for category, terms in categories.items():
        for term in terms:
            count = text_lower.count(term.lower())
            if count > 0:
                scores[category] = scores.get(category, 0) + count

    if not scores:
        return None

    return max(scores, key=scores.get)


def extract_sentence_details(text: str) -> str | None:
    """Extract sentencing details (e.g., '25 years in prison')."""
    if not text:
        return None

    patterns = [
        r"sentenced to (\d+[\s-]+(?:years?|months?)(?: (?:and|to) \d+[\s-]+(?:years?|months?))? in prison)",
        r"sentenced to (life (?:in prison|without parole|imprisonment))",
        r"sentenced to (\d+[\s-]+(?:years?|months?) in (?:prison|jail))",
        r"sentenced to (death)",
        r"sentenced to (\d+[\s-]+(?:years?|months?)(?:\s+(?:to|and)\s+\d+[\s-]+(?:years?|months?))?)",
        r"(\d+[\s-]+(?:years?|months?) (?:in )?(?:prison|jail) (?:sentence|term))",
        r"(life sentence|life imprisonment|life in prison|life without parole)",
        r"received (?:a )?(\d+[\s-]+(?:year|month)[\s-]+(?:prison |jail )?sentence)",
        r"facing (\d+[\s-]+(?:years?|months?) (?:in )?(?:prison|jail))",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    return None


def analyze_article(title: str, text: str | None) -> dict:
    """Run all extraction on an article. Returns dict with state, gender, crime_type, sentence_details."""
    combined = title
    if text:
        combined = f"{title} {text}"

    return {
        "state": extract_state(combined),
        "gender": extract_gender(combined),
        "crime_type": extract_crime_type(combined),
        "sentence_details": extract_sentence_details(combined),
    }
