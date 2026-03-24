from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class CrimeToggle(str, Enum):
    death = "death"
    serious = "serious"
    both = "both"


class Gender(str, Enum):
    any = "any"
    male = "male"
    female = "female"


class SearchRequest(BaseModel):
    gender: Gender = Gender.any
    state: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    crime_toggle: CrimeToggle = CrimeToggle.both
    custom_keywords: Optional[list[str]] = None
    deep_research: bool = False
    target_count: int = 50


class ArticleResult(BaseModel):
    title: str
    url: str
    published_date: Optional[str] = None
    source: Optional[str] = None
    state: Optional[str] = None
    gender: Optional[str] = None
    crime_type: Optional[str] = None
    sentence_details: Optional[str] = None
    snippet: Optional[str] = None
    source_type: Optional[str] = None
    defendant_name: Optional[str] = None
    victim_name: Optional[str] = None
    case_summary: Optional[str] = None
    quality_score: Optional[int] = None
    is_sentencing: Optional[bool] = None


class SearchResponse(BaseModel):
    results: list[ArticleResult]
    total_count: int
    query_used: str
    duplicates_filtered: int = 0
    sheets_url: Optional[str] = None
    source_breakdown: Optional[dict] = None
    ai_filtered: int = 0
    ai_analyzed: bool = False


class SavedSearchOut(BaseModel):
    id: int
    name: str
    search_params: dict
    created_at: str
