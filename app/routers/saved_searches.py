import json
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.database import save_search_config, get_saved_searches, delete_saved_search

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


class SaveSearchRequest(BaseModel):
    name: str
    search_params: dict


@router.get("/saved-searches", response_class=HTMLResponse)
async def saved_searches_page(request: Request):
    searches = await get_saved_searches()
    parsed = []
    for s in searches:
        params = s.get("search_params", "{}")
        if isinstance(params, str):
            params = json.loads(params)
        parsed.append({**s, "search_params": params})
    return templates.TemplateResponse(
        request, "saved_searches.html", {"searches": parsed}
    )


@router.get("/api/saved-searches")
async def list_saved_searches():
    searches = await get_saved_searches()
    result = []
    for s in searches:
        params = s.get("search_params", "{}")
        if isinstance(params, str):
            params = json.loads(params)
        result.append({
            "id": s["id"],
            "name": s["name"],
            "search_params": params,
            "created_at": s["created_at"],
        })
    return result


@router.post("/api/saved-searches")
async def create_saved_search(req: SaveSearchRequest):
    search_id = await save_search_config(req.name, req.search_params)
    return {"id": search_id, "name": req.name}


@router.delete("/api/saved-searches/{search_id}")
async def remove_saved_search(search_id: int):
    await delete_saved_search(search_id)
    return {"status": "deleted"}
