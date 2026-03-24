from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "tripoli.db"
    gnews_max_results: int = 50
    request_delay_seconds: float = 1.0
    fetch_full_text: bool = False
    gnews_language: str = "en"
    gnews_country: str = "US"

    # SerpAPI
    serpapi_key: str = ""

    # AI Analysis (Claude)
    anthropic_api_key: str = ""
    ai_analysis_enabled: bool = True
    ai_quality_threshold: int = 60
    ai_model: str = "claude-haiku-4-5-20251001"

    # Google Sheets
    google_sheets_enabled: bool = False
    google_service_account_file: str = "service_account.json"
    google_sheets_max_articles: int = 50
    google_sheets_share_email: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
