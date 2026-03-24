from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routers import search, export, saved_searches, articles


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Tripoli - Sentencing Article Finder", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(search.router)
app.include_router(export.router)
app.include_router(saved_searches.router)
app.include_router(articles.router)
