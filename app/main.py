"""TM Parts Finder — FastAPI application."""
from fastapi import FastAPI, Request, Query
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from app import db

app = FastAPI(title="TM Parts Finder")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/")
async def home(request: Request):
    """Equipment selector — home page."""
    connected = db.is_connected()
    equipment = []
    if connected:
        try:
            equipment = db.list_equipment()
        except Exception:
            pass
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"connected": connected, "equipment": equipment},
    )


@app.get("/search")
async def search(
    request: Request,
    equip: str = Query(..., description="Equipment ID"),
    q: str = Query("", description="Search query"),
):
    """Search PMCS items and parts for the selected equipment."""
    connected = db.is_connected()
    equipment = None
    results = []
    if connected and equip:
        try:
            equipment = db.get_equipment(equip)
            if q.strip():
                results = db.search(equip, q.strip())
        except Exception:
            pass
    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "connected": connected,
            "equipment": equipment,
            "query": q,
            "results": results,
        },
    )


@app.get("/item/{item_id}")
async def item_detail(request: Request, item_id: str):
    """PMCS item detail view."""
    connected = db.is_connected()
    item = None
    if connected:
        try:
            item = db.get_pmcs_item(item_id)
        except Exception:
            pass
    if item is None:
        return templates.TemplateResponse(
            request=request,
            name="search.html",
            context={
                "connected": connected,
                "equipment": None,
                "query": "",
                "results": [],
                "error": "Item not found.",
            },
        )
    equipment = db.get_equipment(item["equipment_id"])
    return templates.TemplateResponse(
        request=request,
        name="item.html",
        context={"connected": connected, "equipment": equipment, "item": item},
    )
