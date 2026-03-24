import asyncio
import pandas as pd
import streamlit as st

# Patch config before any app imports so Streamlit secrets are used
from app.config import settings
try:
    if st.secrets.get("SERPAPI_KEY"):
        settings.serpapi_key = st.secrets["SERPAPI_KEY"]
    if st.secrets.get("ANTHROPIC_API_KEY"):
        settings.anthropic_api_key = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    pass  # secrets not configured yet, fall back to .env

from app.database import (
    init_db, save_search_history, save_articles, get_all_articles,
    get_existing_urls, get_existing_fingerprints, update_article,
    delete_article, delete_all_articles, add_article,
    get_saved_searches, save_search_config, delete_saved_search,
)
from app.services.query_builder import build_query, get_query_variation, build_query_for_source
from app.services import news_fetcher
from app.services.ai_analyzer import analyze_batch
from app.services.dedup import deduplicate_results, deduplicate_with_fingerprints, normalize_url
from app.services.date_utils import parse_published_date
from app.models import ArticleResult

US_STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
    "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
    "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
    "West Virginia", "Wisconsin", "Wyoming",
]

MAX_ROUNDS = 10


def run_async(coro):
    """Run an async coroutine from sync Streamlit code."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# Init DB on startup
run_async(init_db())

st.set_page_config(page_title="Tripoli", page_icon="🔍", layout="wide")

# Dark theme CSS
st.markdown("""
<style>
    .quality-high { color: #34d399; font-weight: 700; }
    .quality-mid { color: #fbbf24; font-weight: 700; }
    .quality-low { color: #f87171; font-weight: 700; }
    .source-badge {
        display: inline-block; padding: 2px 8px; border-radius: 4px;
        font-size: 0.75rem; font-weight: 600;
    }
    .stDataFrame { font-size: 0.85rem; }
</style>
""", unsafe_allow_html=True)


# --- Search pipeline (reused from search.py) ---

async def _fetch_round(crime_toggle, state, gender, custom_keywords, date_from, date_to, deep_research, query):
    """Fetch articles from all sources for one round."""
    tasks = [news_fetcher.search_serpapi(query, date_from, date_to, max_results=50)]
    if deep_research:
        web_query = build_query_for_source("google_web", crime_toggle, state, gender, custom_keywords)
        fb_query = build_query_for_source("facebook", crime_toggle, state, gender, custom_keywords)
        yt_query = build_query_for_source("youtube", crime_toggle, state, gender, custom_keywords)
        tasks.append(news_fetcher.search_serpapi_web(web_query, date_from, date_to, max_results=20))
        tasks.append(news_fetcher.search_serpapi_facebook(fb_query, date_from, date_to, max_results=10))
        tasks.append(news_fetcher.search_serpapi_youtube(yt_query, date_from, date_to, max_results=15))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    combined = []
    for r in results:
        if isinstance(r, list):
            combined.extend(r)
    return combined


async def _analyze_round(raw_articles):
    """AI analyze a batch of articles. Returns (enriched, filtered_count)."""
    if not settings.ai_analysis_enabled or not settings.anthropic_api_key:
        return raw_articles, 0
    enriched = await analyze_batch(raw_articles)
    threshold = settings.ai_quality_threshold
    filtered = [a for a in enriched if (a.get("quality_score") or 0) >= threshold]
    return filtered, len(enriched) - len(filtered)


def _apply_filters(articles, date_from, date_to, state, gender):
    """Apply post-fetch filters."""
    filtered = []
    for a in articles:
        # Date safety net
        if date_from or date_to:
            pub = parse_published_date(a.get("published_date", ""))
            if pub:
                if date_from and pub < date_from:
                    continue
                if date_to and pub > date_to:
                    continue
        # State filter
        if state:
            article_state = (a.get("state") or "").lower()
            if state.lower() not in article_state:
                filtered.append(a)  # keep if state doesn't match but let AI handle it
                continue
        # Gender filter
        if gender and gender != "any":
            article_gender = (a.get("gender") or "").lower()
            if article_gender and article_gender != gender.lower():
                continue
        filtered.append(a)
    return filtered


def _to_article_dict(r):
    return {
        "title": r.get("title", ""),
        "url": r.get("url", ""),
        "published_date": r.get("published_date"),
        "source": r.get("source"),
        "state": r.get("state"),
        "gender": r.get("gender"),
        "crime_type": r.get("crime_type"),
        "sentence_details": r.get("sentence_details"),
        "snippet": r.get("snippet"),
        "source_type": r.get("source_type"),
        "defendant_name": r.get("defendant_name"),
        "victim_name": r.get("victim_name"),
        "case_summary": r.get("case_summary"),
        "quality_score": r.get("quality_score"),
        "is_sentencing": r.get("is_sentencing"),
    }


async def run_search(crime_toggle, state, gender, date_from, date_to, custom_keywords, deep_research, target_count, progress_callback=None):
    """Full multi-round search pipeline."""
    target = min(target_count, 200)
    all_results = []
    all_queries = []
    total_ai_filtered = 0
    total_dupes = 0
    ai_analyzed = False
    seen_urls = set()

    for round_num in range(MAX_ROUNDS):
        if len(all_results) >= target:
            break

        if round_num == 0:
            query = build_query(crime_toggle, state, gender, custom_keywords)
        else:
            query = get_query_variation(round_num - 1, crime_toggle, state, gender, custom_keywords)
            if not query:
                break

        all_queries.append(query)
        if progress_callback:
            progress_callback(f"Round {round_num + 1}: Searching '{query[:60]}...' ({len(all_results)}/{target} found)")

        raw = await _fetch_round(crime_toggle, state, gender, custom_keywords, date_from, date_to, deep_research, query)
        if not raw:
            continue

        enriched, round_filtered = await _analyze_round(raw)
        total_ai_filtered += round_filtered
        if enriched and any(a.get("quality_score") is not None for a in enriched):
            ai_analyzed = True

        filtered = _apply_filters(enriched, date_from, date_to, state, gender)

        existing_urls = await get_existing_urls()
        combined_urls = existing_urls | seen_urls
        deduped, url_dupes = deduplicate_results(filtered, combined_urls)
        total_dupes += url_dupes

        if ai_analyzed and deduped:
            try:
                existing_fps = await get_existing_fingerprints()
                session_fps = [{"defendant_name": r.get("defendant_name"), "crime_type": r.get("crime_type"), "location_state": r.get("state")} for r in all_results if r.get("defendant_name")]
                all_fps = existing_fps + session_fps
                deduped, fp_dupes = deduplicate_with_fingerprints(deduped, all_fps)
                total_dupes += fp_dupes
            except Exception:
                pass

        for article in deduped:
            seen_urls.add(normalize_url(article.get("url", "")))
        all_results.extend(deduped)

    all_results = all_results[:target]

    # Save to DB
    combined_query = " | ".join(all_queries[:3])
    if len(all_queries) > 3:
        combined_query += f" (+{len(all_queries) - 3} more)"
    search_params = {
        "crime_toggle": crime_toggle, "state": state, "gender": gender,
        "date_from": str(date_from) if date_from else None,
        "date_to": str(date_to) if date_to else None,
        "custom_keywords": custom_keywords, "deep_research": deep_research,
        "target_count": target_count,
    }
    search_id = await save_search_history(search_params, combined_query, len(all_results))
    article_dicts = [_to_article_dict(r) for r in all_results]
    await save_articles(search_id, article_dicts)

    return {
        "results": article_dicts,
        "total_count": len(all_results),
        "query_used": combined_query,
        "duplicates_filtered": total_dupes,
        "ai_filtered": total_ai_filtered,
        "ai_analyzed": ai_analyzed,
    }


# --- Navigation ---
page = st.sidebar.radio("Navigation", ["Search", "Articles", "Saved Searches"], index=0)


# ==================== SEARCH PAGE ====================
if page == "Search":
    st.title("Tripoli — Sentencing Article Finder")

    with st.form("search_form"):
        col1, col2 = st.columns(2)
        with col1:
            crime_toggle = st.radio("Crime Type", ["death", "serious", "both"], index=2, horizontal=True)
            gender = st.selectbox("Gender", ["any", "male", "female"])
            state = st.selectbox("US State", ["Any State"] + US_STATES)
            if state == "Any State":
                state = None

        with col2:
            date_from = st.date_input("Date From", value=None)
            date_to = st.date_input("Date To", value=None)
            custom_kw = st.text_input("Custom Keywords (comma-separated)", placeholder="e.g. restaurant, shooting, robbery")
            custom_keywords = [k.strip() for k in custom_kw.split(",") if k.strip()] if custom_kw else None

        col3, col4 = st.columns(2)
        with col3:
            target_count = st.number_input("Target Cases", min_value=5, max_value=200, value=50, step=5)
        with col4:
            deep_research = st.checkbox("Deep Research (4 sources)", value=True)
            st.caption("Searches Google News, Web, Facebook, and YouTube")

        submitted = st.form_submit_button("Search", type="primary", use_container_width=True)

    # Save search button
    col_save, col_export = st.columns(2)
    with col_save:
        if st.button("Save Current Search Config"):
            name = st.session_state.get("save_name", "")
            if not name:
                st.session_state["show_save_dialog"] = True

    if st.session_state.get("show_save_dialog"):
        save_name = st.text_input("Search name", key="save_name_input")
        if st.button("Confirm Save") and save_name:
            params = {
                "crime_toggle": crime_toggle, "state": state, "gender": gender,
                "custom_keywords": custom_keywords,
            }
            run_async(save_search_config(save_name, params))
            st.success(f"Saved '{save_name}'")
            st.session_state["show_save_dialog"] = False

    if submitted:
        status = st.empty()
        progress = st.progress(0)

        def update_status(msg):
            status.info(msg)

        with st.spinner("Searching..."):
            data = run_async(run_search(
                crime_toggle, state, gender, date_from, date_to,
                custom_keywords, deep_research, target_count,
                progress_callback=update_status,
            ))

        progress.progress(100)

        # Stats
        msg = f"Found **{data['total_count']}** articles."
        if data["duplicates_filtered"] > 0:
            msg += f" {data['duplicates_filtered']} duplicates filtered."
        if data["ai_filtered"] > 0:
            msg += f" {data['ai_filtered']} non-sentencing filtered by AI."
        status.success(msg)
        st.caption(f"Query: `{data['query_used']}`")

        # Results table
        if data["results"]:
            df = pd.DataFrame(data["results"])
            display_cols = ["title", "defendant_name", "published_date", "source", "state",
                          "crime_type", "sentence_details", "quality_score", "source_type", "url"]
            display_cols = [c for c in display_cols if c in df.columns]
            st.dataframe(
                df[display_cols],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "title": st.column_config.TextColumn("Title", width="large"),
                    "defendant_name": st.column_config.TextColumn("Defendant"),
                    "published_date": st.column_config.TextColumn("Date"),
                    "source": st.column_config.TextColumn("Source"),
                    "state": st.column_config.TextColumn("State"),
                    "crime_type": st.column_config.TextColumn("Crime"),
                    "sentence_details": st.column_config.TextColumn("Sentence"),
                    "quality_score": st.column_config.NumberColumn("Quality", format="%d"),
                    "source_type": st.column_config.TextColumn("Type"),
                    "url": st.column_config.LinkColumn("URL", display_text="Link"),
                },
            )

            # CSV export
            csv = df[display_cols].to_csv(index=False)
            st.download_button("Download CSV", csv, "tripoli_results.csv", "text/csv")
        else:
            st.warning("No articles found. Try broadening your search.")


# ==================== ARTICLES PAGE ====================
elif page == "Articles":
    st.title("All Articles")

    search_q = st.text_input("Search articles", placeholder="Filter by title, source, state, crime type...")

    articles_data, total = run_async(get_all_articles(page=1, per_page=500, search=search_q))
    st.caption(f"{total} articles total")

    if articles_data:
        df = pd.DataFrame(articles_data)
        display_cols = ["id", "title", "defendant_name", "url", "published_date",
                       "source", "state", "crime_type", "sentence_details", "quality_score"]
        display_cols = [c for c in display_cols if c in df.columns]

        edited_df = st.data_editor(
            df[display_cols],
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "title": st.column_config.TextColumn("Title", width="large"),
                "defendant_name": st.column_config.TextColumn("Defendant"),
                "url": st.column_config.LinkColumn("URL"),
                "published_date": st.column_config.TextColumn("Date"),
                "source": st.column_config.TextColumn("Source"),
                "state": st.column_config.TextColumn("State"),
                "crime_type": st.column_config.TextColumn("Crime"),
                "sentence_details": st.column_config.TextColumn("Sentence"),
                "quality_score": st.column_config.NumberColumn("Q", format="%d"),
            },
            key="article_editor",
        )

        # CSV export
        csv = df[display_cols].to_csv(index=False)
        st.download_button("Download CSV", csv, "tripoli_articles.csv", "text/csv")

        # Delete all
        if st.button("Delete All Articles", type="secondary"):
            run_async(delete_all_articles())
            st.rerun()
    else:
        st.info("No articles yet. Run a search to get started.")


# ==================== SAVED SEARCHES PAGE ====================
elif page == "Saved Searches":
    st.title("Saved Searches")

    searches_raw = run_async(get_saved_searches())
    import json

    if searches_raw:
        for s in searches_raw:
            params = s.get("search_params", "{}")
            if isinstance(params, str):
                params = json.loads(params)

            with st.container(border=True):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.subheader(s["name"])
                    st.caption(f"Created: {s.get('created_at', '')}")
                    badges = []
                    if params.get("crime_toggle"):
                        badges.append(params["crime_toggle"].capitalize())
                    if params.get("state"):
                        badges.append(params["state"])
                    if params.get("gender") and params["gender"] != "any":
                        badges.append(params["gender"].capitalize())
                    if params.get("custom_keywords"):
                        badges.append("+ Keywords")
                    st.write(" · ".join(badges))
                with col2:
                    if st.button("Delete", key=f"del_{s['id']}"):
                        run_async(delete_saved_search(s["id"]))
                        st.rerun()
    else:
        st.info("No saved searches yet. Run a search and save it.")
