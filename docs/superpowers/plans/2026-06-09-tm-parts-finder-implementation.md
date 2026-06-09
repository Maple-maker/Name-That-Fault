# TM Parts Finder — Maintenance Copilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a searchable database of Army Technical Manuals where operators select equipment, describe symptoms in their own words, and get back PMCS item numbers, technical status, NSNs, and TM references.

**Architecture:** FastAPI app on Railway, Supabase Postgres with full-text search, server-rendered Jinja2 templates, dark AEGIS theme. Extraction pipeline uses pdfplumber + PyMuPDF for digital PDFs. No JavaScript framework — CSS Grid + Flexbox for responsive UI.

**Tech Stack:** Python 3.12+, FastAPI, Supabase Python client, pdfplumber, PyMuPDF, Jinja2, ocrmypdf

---

## File Structure

```
tm-parts-finder/
├── schema.sql                          # Database tables, indexes, search function
├── app/
│   ├── main.py                         # FastAPI routes + search logic
│   ├── config.py                       # .env settings
│   ├── db.py                           # Supabase client + query functions
│   ├── templates/
│   │   ├── base.html                   # Layout + nav shell
│   │   ├── index.html                  # Equipment selector (home page)
│   │   └── search.html                 # Search bar + results + inline detail
│   └── static/
│       └── style.css                   # Dark AEGIS theme
├── ingest/
│   ├── extract.py                      # PDF → raw text rows + table rows
│   ├── load.py                         # Cleaned rows → Supabase
│   ├── load_all.py                     # Batch: walk TMs/ dir, extract + load
│   └── equipment_csv.py               # Output equipment.csv for image sourcing
├── requirements.txt
├── .env.example
├── .gitignore
└── Procfile
```

**Boundaries:**
- `schema.sql` owns all DDL — tables, indexes, triggers, search function. The only file you run in Supabase SQL editor.
- `app/db.py` is the single interface to Supabase — all queries go through it. Routes never call Supabase directly.
- `app/main.py` owns routing and search orchestration. Calls `db.py` for data, renders templates.
- `ingest/extract.py` knows how to read PDFs. `ingest/load.py` knows how to write to Supabase. `ingest/load_all.py` orchestrates both.
- Templates are pure presentation — no business logic, no direct DB calls.

---

### Task 1: Database Schema

**Files:**
- Create: `schema.sql`

- [ ] **Step 1: Write schema.sql with tables, indexes, and search function**

```sql
-- TM Parts Finder — Database Schema
-- Run this in Supabase SQL Editor

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- TABLES
-- ============================================================

CREATE TABLE equipment (
    id          text PRIMARY KEY,
    name        text NOT NULL,
    nomenclature text,
    image_url   text,
    tm_number   text NOT NULL,
    created_at  timestamptz DEFAULT now()
);

CREATE TABLE pmcs_items (
    id               uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    equipment_id     text NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
    item_number      text NOT NULL,
    interval         text,           -- Before, During, After, Weekly, Monthly
    item_to_inspect  text NOT NULL,
    technical_status text,           -- "Not fully mission capable if..."
    nsn              text,
    tm_ref           text,           -- "TM 9-2320-280-10, Page 2-47"
    search_vector    tsvector GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(item_number, '') || ' ' ||
                               coalesce(item_to_inspect, '') || ' ' ||
                               coalesce(technical_status, '') || ' ' ||
                               coalesce(nsn, '') || ' ' ||
                               coalesce(interval, ''))
    ) STORED,
    created_at       timestamptz DEFAULT now()
);

CREATE TABLE parts (
    id            uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    equipment_id  text NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
    nsn           text NOT NULL,
    part_number   text,
    nomenclature  text NOT NULL,
    source_tm     text,
    page_ref      text,
    created_at    timestamptz DEFAULT now()
);

-- ============================================================
-- INDEXES
-- ============================================================

-- Full-text search on pmcs_items
CREATE INDEX idx_pmcs_search ON pmcs_items USING GIN(search_vector);

-- Trigram indexes for fuzzy/partial matching
CREATE INDEX idx_pmcs_inspect_trgm ON pmcs_items USING GIN(item_to_inspect gin_trgm_ops);
CREATE INDEX idx_pmcs_nsn_trgm ON pmcs_items USING GIN(nsn gin_trgm_ops);
CREATE INDEX idx_parts_nomenclature_trgm ON parts USING GIN(nomenclature gin_trgm_ops);
CREATE INDEX idx_parts_nsn_trgm ON parts USING GIN(nsn gin_trgm_ops);

-- Equipment-scoped lookups
CREATE INDEX idx_pmcs_equipment ON pmcs_items(equipment_id);
CREATE INDEX idx_parts_equipment ON parts(equipment_id);

-- ============================================================
-- SEARCH FUNCTION
-- ============================================================

-- Combined full-text + trigram search, equipment-scoped
-- Returns ranked results from both pmcs_items and parts
CREATE OR REPLACE FUNCTION search_equipment(
    equip_id text,
    query text
)
RETURNS TABLE(
    source          text,
    id              uuid,
    item_number     text,
    interval        text,
    item_to_inspect text,
    technical_status text,
    nsn             text,
    part_number     text,
    nomenclature    text,
    tm_ref          text,
    source_tm       text,
    page_ref        text,
    rank            real
) LANGUAGE plpgsql STABLE AS $$
BEGIN
    RETURN QUERY

    -- Full-text search across pmcs_items
    SELECT
        'pmcs'::text,
        pi.id,
        pi.item_number,
        pi.interval,
        pi.item_to_inspect,
        pi.technical_status,
        pi.nsn,
        NULL::text,
        NULL::text,
        pi.tm_ref,
        NULL::text,
        NULL::text,
        ts_rank(pi.search_vector, websearch_to_tsquery('english', query)) AS rank
    FROM pmcs_items pi
    WHERE pi.equipment_id = equip_id
      AND pi.search_vector @@ websearch_to_tsquery('english', query)

    UNION ALL

    -- Trigram fallback for pmcs_items (when full-text yields nothing useful)
    SELECT
        'pmcs'::text,
        pi.id,
        pi.item_number,
        pi.interval,
        pi.item_to_inspect,
        pi.technical_status,
        pi.nsn,
        NULL::text,
        NULL::text,
        pi.tm_ref,
        NULL::text,
        NULL::text,
        GREATEST(
            similarity(pi.item_to_inspect, query),
            similarity(coalesce(pi.technical_status, ''), query),
            similarity(coalesce(pi.nsn, ''), query)
        ) AS rank
    FROM pmcs_items pi
    WHERE pi.equipment_id = equip_id
      AND (
          similarity(pi.item_to_inspect, query) > 0.15
          OR similarity(coalesce(pi.technical_status, ''), query) > 0.15
          OR similarity(coalesce(pi.nsn, ''), query) > 0.15
      )

    UNION ALL

    -- Full-text search across parts
    SELECT
        'parts'::text,
        p.id,
        NULL::text,
        NULL::text,
        NULL::text,
        NULL::text,
        p.nsn,
        p.part_number,
        p.nomenclature,
        NULL::text,
        p.source_tm,
        p.page_ref,
        ts_rank(
            to_tsvector('english', coalesce(p.nomenclature, '') || ' ' ||
                                    coalesce(p.nsn, '') || ' ' ||
                                    coalesce(p.part_number, '')),
            websearch_to_tsquery('english', query)
        ) AS rank
    FROM parts p
    WHERE p.equipment_id = equip_id
      AND to_tsvector('english', coalesce(p.nomenclature, '') || ' ' ||
                                   coalesce(p.nsn, '') || ' ' ||
                                   coalesce(p.part_number, ''))
          @@ websearch_to_tsquery('english', query)

    UNION ALL

    -- Trigram fallback for parts
    SELECT
        'parts'::text,
        p.id,
        NULL::text,
        NULL::text,
        NULL::text,
        NULL::text,
        p.nsn,
        p.part_number,
        p.nomenclature,
        NULL::text,
        p.source_tm,
        p.page_ref,
        GREATEST(
            similarity(p.nomenclature, query),
            similarity(coalesce(p.nsn, ''), query),
            similarity(coalesce(p.part_number, ''), query)
        ) AS rank
    FROM parts p
    WHERE p.equipment_id = equip_id
      AND (
          similarity(p.nomenclature, query) > 0.15
          OR similarity(coalesce(p.nsn, ''), query) > 0.15
          OR similarity(coalesce(p.part_number, ''), query) > 0.15
      )

    ORDER BY rank DESC
    LIMIT 25;
END;
$$;
```

- [ ] **Step 2: Run schema in Supabase SQL Editor**

Go to your Supabase project → SQL Editor → paste `schema.sql` → Run.

Verify:
```sql
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
```
Expected: `equipment`, `parts`, `pmcs_items`

- [ ] **Step 3: Test search function with sample data**

```sql
INSERT INTO equipment (id, name, nomenclature, tm_number)
VALUES ('test-hmmwv', 'HMMWV M1151 Test', 'Truck, Utility', 'TM 9-2320-280-10');

INSERT INTO pmcs_items (equipment_id, item_number, interval, item_to_inspect, technical_status, nsn, tm_ref)
VALUES
  ('test-hmmwv', '23', 'Before', 'Engine Start', 'Engine fails to crank — starter motor inoperative', '2920-01-111-1111', 'TM 9-2320-280-10, Page 2-47'),
  ('test-hmmwv', '6', 'Before', 'Engine Compartment', 'Oil leaks visible on engine block', '2815-01-222-2222', 'TM 9-2320-280-10, Page 2-12'),
  ('test-hmmwv', '8', 'During', 'Instruments and Gauges', 'Oil pressure gauge inoperative', '6620-01-333-3333', 'TM 9-2320-280-10, Page 2-18');

SELECT * FROM search_equipment('test-hmmwv', 'engine');
-- Expected: 2+ rows, Item #23 and #6 ranked by relevance

SELECT * FROM search_equipment('test-hmmwv', 'gage');
-- Expected: Item #8 (trigram matches "gauge" → "gage")

-- Cleanup test data
DELETE FROM pmcs_items WHERE equipment_id = 'test-hmmwv';
DELETE FROM equipment WHERE id = 'test-hmmwv';
```

- [ ] **Step 4: Commit**

```bash
git add schema.sql
git commit -m "feat: add database schema with full-text search and trigram fallback"
```

---

### Task 2: App Scaffold (Config + DB + FastAPI Shell)

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `Procfile`
- Create: `app/config.py`
- Create: `app/db.py`
- Create: `app/main.py` (shell with routes)

- [ ] **Step 1: Write requirements.txt**

```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
supabase>=2.6.0
python-dotenv>=1.0.0
pdfplumber>=0.11.0
PyMuPDF>=1.27.0
ocrmypdf>=16.0.0
jinja2>=3.1.0
```

- [ ] **Step 2: Write .env.example**

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
SUPABASE_SERVICE_KEY=your-service-role-key
```

- [ ] **Step 3: Write Procfile**

```
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

- [ ] **Step 4: Write app/config.py**

```python
"""Read settings from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

DATABASE_CONNECTED = bool(SUPABASE_URL and SUPABASE_KEY)
```

- [ ] **Step 5: Write app/db.py**

```python
"""Supabase client and query functions — single interface to the database."""
from supabase import create_client, Client
from app import config

_client: Client | None = None


def get_client() -> Client:
    """Lazy-load Supabase client so the app boots before credentials exist."""
    global _client
    if _client is None:
        if not config.DATABASE_CONNECTED:
            raise RuntimeError("Supabase not configured. Set SUPABASE_URL and SUPABASE_KEY.")
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    return _client


def is_connected() -> bool:
    """Check if Supabase credentials are configured."""
    return config.DATABASE_CONNECTED


def list_equipment() -> list[dict]:
    """Return all equipment rows, ordered by name."""
    client = get_client()
    result = client.table("equipment").select("*").order("name").execute()
    return result.data


def get_equipment(equipment_id: str) -> dict | None:
    """Return a single equipment row by ID."""
    client = get_client()
    result = client.table("equipment").select("*").eq("id", equipment_id).execute()
    if result.data:
        return result.data[0]
    return None


def search(equipment_id: str, query: str) -> list[dict]:
    """Run combined full-text + trigram search via the stored function."""
    client = get_client()
    result = client.rpc("search_equipment", {
        "equip_id": equipment_id,
        "query": query,
    }).execute()
    return result.data


def get_pmcs_item(item_id: str) -> dict | None:
    """Return a single PMCS item by UUID."""
    client = get_client()
    result = client.table("pmcs_items").select("*").eq("id", item_id).execute()
    if result.data:
        return result.data[0]
    return None


def insert_equipment_batch(rows: list[dict]) -> None:
    """Insert equipment rows, ignoring conflicts on primary key."""
    client = get_client()
    client.table("equipment").upsert(rows).execute()


def insert_pmcs_batch(rows: list[dict]) -> None:
    """Insert PMCS item rows."""
    client = get_client()
    client.table("pmcs_items").insert(rows).execute()


def insert_parts_batch(rows: list[dict]) -> None:
    """Insert parts rows."""
    client = get_client()
    client.table("parts").insert(rows).execute()
```

- [ ] **Step 6: Write app/main.py (shell)**

```python
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
    return templates.TemplateResponse("index.html", {
        "request": request,
        "connected": connected,
        "equipment": equipment,
    })


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
    return templates.TemplateResponse("search.html", {
        "request": request,
        "connected": connected,
        "equipment": equipment,
        "query": q,
        "results": results,
    })


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
        return templates.TemplateResponse("search.html", {
            "request": request,
            "connected": connected,
            "equipment": None,
            "query": "",
            "results": [],
            "error": "Item not found.",
        })
    equipment = db.get_equipment(item["equipment_id"])
    return templates.TemplateResponse("item.html", {
        "request": request,
        "connected": connected,
        "equipment": equipment,
        "item": item,
    })
```

- [ ] **Step 7: Verify app boots**

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 — expect "Database not connected" banner (no `.env` yet). The app boots but shows no data. This is correct behavior.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt .env.example Procfile app/
git commit -m "feat: add FastAPI scaffold with config, db client, and route shells"
```

---

### Task 3: Web UI — Templates and CSS

**Files:**
- Create: `app/templates/base.html`
- Create: `app/templates/index.html`
- Create: `app/templates/search.html`
- Create: `app/templates/item.html`
- Create: `app/static/style.css`

- [ ] **Step 1: Write app/static/style.css**

```css
/* TM Parts Finder — Dark AEGIS Theme */
:root {
    --bg: #0d0d0d;
    --surface: #1a1a1a;
    --border: #2a2a2a;
    --text: #e0e0e0;
    --text-muted: #888;
    --accent: #4fc3f7;
    --accent-dim: rgba(79, 195, 247, 0.1);
    --danger: #ef5350;
    --success: #81c784;
    --radius: 8px;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    line-height: 1.5;
}

.container { max-width: 800px; margin: 0 auto; padding: 16px; }

/* Header */
.header {
    padding: 16px 0;
    border-bottom: 1px solid var(--border);
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.header h1 { font-size: 1.25rem; font-weight: 700; color: var(--text); }
.header a { color: var(--accent); text-decoration: none; font-size: 0.875rem; }
.header a:hover { text-decoration: underline; }

/* Banner */
.banner {
    background: #332200;
    color: #ffb74d;
    padding: 10px 16px;
    border-radius: var(--radius);
    margin-bottom: 16px;
    font-size: 0.875rem;
}

/* Equipment Cards */
.equipment-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 12px;
}
.equipment-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
    text-decoration: none;
    color: var(--text);
    transition: border-color 0.15s;
}
.equipment-card:hover, .equipment-card:focus { border-color: var(--accent); }
.equipment-card img {
    width: 100%; height: 140px; object-fit: cover;
    background: var(--border);
}
.equipment-card .card-body { padding: 12px; }
.equipment-card .card-body h3 { font-size: 1rem; margin-bottom: 4px; }
.equipment-card .card-body p { font-size: 0.8rem; color: var(--text-muted); }

/* Search Bar */
.search-bar {
    margin-bottom: 20px;
}
.search-bar form {
    display: flex;
    gap: 8px;
}
.search-bar input[type="search"] {
    flex: 1;
    padding: 12px 16px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text);
    font-size: 1rem;
}
.search-bar input[type="search"]:focus {
    outline: none;
    border-color: var(--accent);
}
.search-bar button {
    padding: 12px 20px;
    background: var(--accent);
    color: #000;
    border: none;
    border-radius: var(--radius);
    font-weight: 600;
    cursor: pointer;
    font-size: 0.9rem;
}
.search-bar button:hover { opacity: 0.9; }

/* Results */
.results-list { list-style: none; }
.result-item {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 14px;
    margin-bottom: 10px;
}
.result-item h3 { font-size: 1rem; margin-bottom: 6px; }
.result-item h3 a { color: var(--accent); text-decoration: none; }
.result-item h3 a:hover { text-decoration: underline; }
.result-meta {
    display: flex; flex-wrap: wrap; gap: 8px 16px;
    font-size: 0.8rem; color: var(--text-muted);
}
.result-meta span { white-space: nowrap; }
.source-tag {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
}
.source-pmcs { background: var(--accent-dim); color: var(--accent); }
.source-parts { background: rgba(129,199,132,0.1); color: var(--success); }

/* Fault highlight */
.fault-status {
    color: var(--danger);
    font-size: 0.85rem;
    margin-top: 4px;
}

/* Equipment breadcrumb */
.breadcrumb {
    font-size: 0.875rem;
    color: var(--text-muted);
    margin-bottom: 16px;
}
.breadcrumb a { color: var(--accent); text-decoration: none; }

/* Item Detail */
.detail-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px;
}
.detail-row {
    display: flex;
    justify-content: space-between;
    padding: 10px 0;
    border-bottom: 1px solid var(--border);
}
.detail-row:last-child { border-bottom: none; }
.detail-label { color: var(--text-muted); font-size: 0.85rem; }
.detail-value { color: var(--text); text-align: right; font-weight: 500; }
.detail-value.fault { color: var(--danger); }

/* Copy button */
.copy-btn {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 6px 12px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--accent);
    cursor: pointer;
    font-size: 0.8rem;
    margin-top: 12px;
}
.copy-btn:hover { border-color: var(--accent); }

/* Empty state */
.empty-state {
    text-align: center;
    padding: 48px 16px;
    color: var(--text-muted);
}
.empty-state p { margin-bottom: 8px; }

/* Back link */
.back-link {
    display: inline-block;
    margin-bottom: 16px;
    color: var(--accent);
    text-decoration: none;
    font-size: 0.875rem;
}
.back-link:hover { text-decoration: underline; }

/* Responsive */
@media (max-width: 500px) {
    .equipment-grid { grid-template-columns: repeat(2, 1fr); }
    .search-bar form { flex-direction: column; }
}
```

- [ ] **Step 2: Write app/templates/base.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TM Parts Finder</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <div class="container">
        <header class="header">
            <h1>🔧 TM Parts Finder</h1>
            <a href="/">← All Equipment</a>
        </header>
        {% if not connected %}
        <div class="banner">⚠️ Database not connected. Set SUPABASE_URL and SUPABASE_KEY in .env</div>
        {% endif %}
        {% block content %}{% endblock %}
    </div>
</body>
</html>
```

- [ ] **Step 3: Write app/templates/index.html**

```html
{% extends "base.html" %}
{% block content %}

<h2 style="margin-bottom: 4px;">Select Equipment</h2>
<p style="color: #888; font-size: 0.9rem; margin-bottom: 20px;">What are you working on?</p>

{% if equipment %}
<div class="equipment-grid">
    {% for eq in equipment %}
    <a href="/search?equip={{ eq.id }}" class="equipment-card">
        {% if eq.image_url %}
        <img src="{{ eq.image_url }}" alt="{{ eq.name }}">
        {% else %}
        <img src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='400' height='140' fill='%231a1a1a'%3E%3Crect width='400' height='140'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='central' text-anchor='middle' fill='%23444' font-size='14'%3ENo Image%3C/text%3E%3C/svg%3E" alt="{{ eq.name }}">
        {% endif %}
        <div class="card-body">
            <h3>{{ eq.name }}</h3>
            <p>{{ eq.nomenclature or eq.tm_number }}</p>
        </div>
    </a>
    {% endfor %}
</div>
{% elif connected %}
<div class="empty-state">
    <p>No equipment loaded yet.</p>
    <p style="font-size: 0.85rem;">Run the ingest pipeline to populate the database.</p>
</div>
{% endif %}

{% endblock %}
```

- [ ] **Step 4: Write app/templates/search.html**

```html
{% extends "base.html" %}
{% block content %}

{% if equipment %}
<div class="breadcrumb">
    <a href="/">Equipment</a> → {{ equipment.name }}
</div>
{% endif %}

<div class="search-bar">
    <form method="get" action="/search">
        <input type="hidden" name="equip" value="{{ equipment.id if equipment else '' }}">
        <input type="search" name="q" placeholder="Describe the symptom or part..." value="{{ query }}" autofocus>
        <button type="submit">Search</button>
    </form>
</div>

{% if results %}
<ul class="results-list">
    {% for r in results %}
    <li class="result-item">
        <h3>
            {% if r.source == 'pmcs' %}
            <a href="/search?equip={{ equipment.id }}&q=item+{{ r.item_number }}">
                Item #{{ r.item_number }}: {{ r.item_to_inspect }}
            </a>
            <span class="source-tag source-pmcs">PMCS</span>
            {% else %}
            <span>{{ r.nomenclature }}</span>
            <span class="source-tag source-parts">PART</span>
            {% endif %}
        </h3>
        <div class="result-meta">
            {% if r.interval %}<span>⏱ {{ r.interval }}</span>{% endif %}
            {% if r.nsn %}<span>📦 NSN: {{ r.nsn }}</span>{% endif %}
            {% if r.tm_ref %}<span>📄 {{ r.tm_ref }}</span>{% endif %}
            {% if r.source_tm %}<span>📄 {{ r.source_tm }}{% if r.page_ref %}, {{ r.page_ref }}{% endif %}</span>{% endif %}
            {% if r.part_number %}<span>🔢 {{ r.part_number }}</span>{% endif %}
        </div>
        {% if r.technical_status %}
        <div class="fault-status">⚠️ {{ r.technical_status }}</div>
        {% endif %}
    </li>
    {% endfor %}
</ul>
{% elif query %}
<div class="empty-state">
    <p>No results found for "{{ query }}".</p>
    <p style="font-size: 0.85rem;">Try different words — "won't start" instead of "engine failure", or search by NSN.</p>
</div>
{% else %}
<div class="empty-state">
    <p>Describe a symptom or part to search.</p>
    <p style="font-size: 0.85rem;">Examples: "engine smoke", "won't start", "oil leak", "5331-01"</p>
</div>
{% endif %}

{% endblock %}
```

- [ ] **Step 5: Write app/templates/item.html**

```html
{% extends "base.html" %}
{% block content %}

<a href="/search?equip={{ equipment.id }}" class="back-link">← Back to {{ equipment.name }}</a>

<div class="detail-card">
    <h2 style="margin-bottom: 4px;">Item #{{ item.item_number }}: {{ item.item_to_inspect }}</h2>
    <span class="source-tag source-pmcs" style="margin-bottom: 16px;">PMCS</span>

    <div style="margin-top: 16px;">
        <div class="detail-row">
            <span class="detail-label">Interval</span>
            <span class="detail-value">{{ item.interval or '—' }}</span>
        </div>
        <div class="detail-row">
            <span class="detail-label">Item to Inspect</span>
            <span class="detail-value">{{ item.item_to_inspect }}</span>
        </div>
        <div class="detail-row">
            <span class="detail-label">Technical Status</span>
            <span class="detail-value fault">{{ item.technical_status or 'No fault criteria listed' }}</span>
        </div>
        <div class="detail-row">
            <span class="detail-label">NSN</span>
            <span class="detail-value">{{ item.nsn or '—' }}</span>
        </div>
        <div class="detail-row">
            <span class="detail-label">TM Reference</span>
            <span class="detail-value">{{ item.tm_ref or '—' }}</span>
        </div>
    </div>

    <button class="copy-btn" onclick="navigator.clipboard.writeText('Item {{ item.item_number }}: {{ item.item_to_inspect }}\nStatus: {{ item.technical_status or '' }}\nNSN: {{ item.nsn or '' }}\nRef: {{ item.tm_ref or '' }}')">
        📋 Copy for paperwork
    </button>
</div>

{% endblock %}
```

- [ ] **Step 6: Verify templates render**

```bash
uvicorn app.main:app --reload
```

Visit:
- http://127.0.0.1:8000/ — equipment selector (empty state, no data yet)
- http://127.0.0.1:8000/search?equip=test&q=engine — search page with "not connected" banner

All pages render without errors, dark theme applied.

- [ ] **Step 7: Commit**

```bash
git add app/templates/ app/static/
git commit -m "feat: add web UI templates with dark AEGIS theme"
```

---

### Task 4: Connect Supabase and Test Search End-to-End

**Files:**
- Modify: `.env` (local only, not committed)

- [ ] **Step 1: Create .env with Supabase credentials**

```bash
cp .env.example .env
# Edit .env with your actual Supabase URL and anon key
```

- [ ] **Step 2: Insert test data via Supabase SQL Editor**

```sql
INSERT INTO equipment (id, name, nomenclature, tm_number)
VALUES ('hmmwv-m1151', 'HMMWV M1151', 'Truck, Utility, Armored', 'TM 9-2320-280-10');

INSERT INTO pmcs_items (equipment_id, item_number, interval, item_to_inspect, technical_status, nsn, tm_ref)
VALUES
  ('hmmwv-m1151', '23', 'Before', 'Engine Start', 'Engine fails to crank — starter motor inoperative', '2920-01-111-1111', 'TM 9-2320-280-10, Page 2-47'),
  ('hmmwv-m1151', '6', 'Before', 'Engine Compartment', 'Oil leaks visible on engine block', '2815-01-222-2222', 'TM 9-2320-280-10, Page 2-12'),
  ('hmmwv-m1151', '8', 'During', 'Instruments and Gauges', 'Oil pressure gauge inoperative', '6620-01-333-3333', 'TM 9-2320-280-10, Page 2-18');

INSERT INTO parts (equipment_id, nsn, part_number, nomenclature, source_tm, page_ref)
VALUES
  ('hmmwv-m1151', '5331-01-444-4444', 'M83521/2-022', 'O-RING', 'TM 9-2320-280-24P', 'Page 4-12'),
  ('hmmwv-m1151', '2920-01-555-5555', '12345678', 'STARTER MOTOR', 'TM 9-2320-280-24P', 'Page 3-22');
```

- [ ] **Step 3: Test end-to-end**

```bash
uvicorn app.main:app --reload
```

Visit:
- http://127.0.0.1:8000/ — should show HMMWV M1151 card
- http://127.0.0.1:8000/search?equip=hmmwv-m1151&q=engine — should return Items #23, #6
- http://127.0.0.1:8000/search?equip=hmmwv-m1151&q=starter — should return Item #23 + Starter Motor part
- http://127.0.0.1:8000/search?equip=hmmwv-m1151&q=gage — trigram: should return Item #8 (gauge ≈ gage)

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: verify Supabase connection and search end-to-end" --allow-empty
```

---

### Task 5: Extraction Pipeline

**Files:**
- Create: `ingest/extract.py`
- Create: `ingest/load.py`
- Create: `ingest/load_all.py`

- [ ] **Step 1: Write ingest/extract.py**

```python
"""Extract text and table rows from a digital PDF."""
import json
import sys
from pathlib import Path
import pdfplumber
import fitz  # PyMuPDF


def extract_full_text(pdf_path: Path) -> str:
    """Extract all text from a PDF using PyMuPDF (fast, works on most digital PDFs)."""
    doc = fitz.open(str(pdf_path))
    pages = []
    for page in doc:
        text = page.get_text()
        if text.strip():
            pages.append(text.strip())
    doc.close()
    return "\n\n".join(pages)


def extract_tables(pdf_path: Path) -> list[list[list[str]]]:
    """Extract all tables from a PDF using pdfplumber."""
    tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_tables = page.extract_tables()
            for tbl in page_tables:
                if tbl and len(tbl) > 1:  # skip empty/single-row tables
                    tables.append(tbl)
    return tables


def classify_table(table: list[list[str]]) -> str | None:
    """Guess if a table is PMCS, parts, or unknown based on column headers.

    Returns 'pmcs', 'parts', or None.
    """
    if not table or not table[0]:
        return None
    headers = " ".join(str(c).lower() for c in table[0] if c)

    pmcs_markers = ["item", "interval", "inspect", "not fully mission capable", "status"]
    parts_markers = ["nsn", "part number", "nomenclature", "niin", "rpstl"]

    pmcs_score = sum(1 for m in pmcs_markers if m in headers)
    parts_score = sum(1 for m in parts_markers if m in headers)

    if pmcs_score >= 2:
        return "pmcs"
    if parts_score >= 2:
        return "parts"
    return None


def table_to_rows(table: list[list[str]], table_type: str, equipment_id: str,
                  tm_number: str, pdf_name: str) -> list[dict]:
    """Convert a classified table to clean dict rows ready for the database."""
    rows = []
    headers = [str(h).strip().lower() if h else "" for h in table[0]]

    for row in table[1:]:
        if not row or all(not c or not str(c).strip() for c in row):
            continue
        cells = [str(c).strip() if c else "" for c in row]

        if table_type == "pmcs":
            rows.append({
                "equipment_id": equipment_id,
                "item_number": cells[0] if len(cells) > 0 else "",
                "interval": cells[1] if len(cells) > 1 else "",
                "item_to_inspect": cells[2] if len(cells) > 2 else "",
                "technical_status": cells[3] if len(cells) > 3 else "",
                "nsn": cells[4] if len(cells) > 4 else "",
                "tm_ref": f"{tm_number} — {pdf_name}",
            })
        elif table_type == "parts":
            rows.append({
                "equipment_id": equipment_id,
                "nsn": cells[0] if len(cells) > 0 else "",
                "part_number": cells[1] if len(cells) > 1 else "",
                "nomenclature": cells[2] if len(cells) > 2 else "",
                "source_tm": tm_number,
                "page_ref": "",
            })

    return rows


def extract_pdf(pdf_path: Path, equipment_id: str, tm_number: str) -> dict:
    """Extract everything from a single PDF.

    Returns:
        {
            "pdf_name": str,
            "full_text": str,
            "pmcs_rows": list[dict],
            "parts_rows": list[dict],
        }
    """
    pdf_name = pdf_path.name
    print(f"  Extracting: {pdf_name} ...")

    full_text = extract_full_text(pdf_path)
    tables = extract_tables(pdf_path)

    pmcs_rows = []
    parts_rows = []

    for tbl in tables:
        tbl_type = classify_table(tbl)
        if tbl_type == "pmcs":
            pmcs_rows.extend(table_to_rows(tbl, "pmcs", equipment_id, tm_number, pdf_name))
        elif tbl_type == "parts":
            parts_rows.extend(table_to_rows(tbl, "parts", equipment_id, tm_number, pdf_name))

    print(f"    → {len(full_text):,} chars text, {len(pmcs_rows)} PMCS rows, {len(parts_rows)} parts rows")

    return {
        "pdf_name": pdf_name,
        "full_text": full_text,
        "pmcs_rows": pmcs_rows,
        "parts_rows": parts_rows,
    }
```

- [ ] **Step 2: Write ingest/load.py**

```python
"""Load extracted rows into Supabase."""
import os
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env")


def get_client():
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def load_equipment(equipment_rows: list[dict]) -> int:
    """Insert equipment rows, upserting on id conflict."""
    if not equipment_rows:
        return 0
    client = get_client()
    result = client.table("equipment").upsert(equipment_rows).execute()
    return len(result.data)


def load_pmcs_items(pmcs_rows: list[dict], batch_size: int = 500) -> int:
    """Insert PMCS item rows in batches."""
    if not pmcs_rows:
        return 0
    client = get_client()
    count = 0
    for i in range(0, len(pmcs_rows), batch_size):
        batch = pmcs_rows[i : i + batch_size]
        client.table("pmcs_items").insert(batch).execute()
        count += len(batch)
    return count


def load_parts(parts_rows: list[dict], batch_size: int = 500) -> int:
    """Insert parts rows in batches."""
    if not parts_rows:
        return 0
    client = get_client()
    count = 0
    for i in range(0, len(parts_rows), batch_size):
        batch = parts_rows[i : i + batch_size]
        client.table("parts").insert(batch).execute()
        count += len(batch)
    return count
```

- [ ] **Step 3: Write ingest/load_all.py**

```python
"""Batch ingest: walk the TMs/ directory, extract every PDF, load into Supabase.

Usage:
    python -m ingest.load_all

Requires:
    - .env with SUPABASE_URL and SUPABASE_SERVICE_KEY
    - PDFs in TMs/ directory
"""
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.extract import extract_pdf
from ingest.load import load_equipment, load_pmcs_items, load_parts


def derive_equipment_id(pdf_name: str) -> str:
    """Derive a stable equipment ID from the PDF filename.

    Example: 'TM 9-2320-280-10 (HMMWV M1151) 2023.pdf' → 'hmmwv-m1151'
    """
    import re
    # Strip extension
    name = Path(pdf_name).stem
    # Try to extract the equipment name from parentheses
    paren_match = re.search(r'\(([^)]+)\)', name)
    if paren_match:
        return paren_match.group(1).lower().replace(" ", "-").replace("/", "-")
    # Fallback: use the first part of the TM number
    tm_match = re.search(r'TM\s+([\d-]+)', name)
    if tm_match:
        return f"tm-{tm_match.group(1)}"
    # Last resort: slugify the filename
    return name.lower().replace(" ", "-")[:50]


def derive_equipment_name(pdf_name: str) -> str:
    """Derive a human-readable equipment name from the PDF filename."""
    import re
    name = Path(pdf_name).stem
    paren_match = re.search(r'\(([^)]+)\)', name)
    if paren_match:
        return paren_match.group(1).strip()
    # Fallback: remove TM prefix and return
    return re.sub(r'^TM\s+[\d-]+\s*', '', name).strip() or name


def derive_tm_number(pdf_name: str) -> str:
    """Extract TM number from PDF filename."""
    import re
    tm_match = re.search(r'(TM\s+[\d-]+)', pdf_name)
    if tm_match:
        return tm_match.group(1)
    return pdf_name


def main():
    tms_dir = Path("TMs")
    if not tms_dir.exists():
        print("ERROR: TMs/ directory not found.")
        sys.exit(1)

    pdfs = sorted(tms_dir.glob("*.pdf"))
    print(f"Found {len(pdfs)} PDFs in TMs/\n")

    total_pmcs = 0
    total_parts = 0
    equipment_seen = set()

    for pdf_path in pdfs:
        equip_id = derive_equipment_id(pdf_path.name)
        equip_name = derive_equipment_name(pdf_path.name)
        tm_number = derive_tm_number(pdf_path.name)

        # Load equipment row (deduplicate)
        if equip_id not in equipment_seen:
            load_equipment([{
                "id": equip_id,
                "name": equip_name,
                "nomenclature": "",
                "tm_number": tm_number,
            }])
            equipment_seen.add(equip_id)
            print(f"  + Equipment: {equip_name} ({equip_id})")

        # Extract
        result = extract_pdf(pdf_path, equip_id, tm_number)

        # Load
        if result["pmcs_rows"]:
            n = load_pmcs_items(result["pmcs_rows"])
            total_pmcs += n
            print(f"    → Loaded {n} PMCS rows")

        if result["parts_rows"]:
            n = load_parts(result["parts_rows"])
            total_parts += n
            print(f"    → Loaded {n} parts rows")

        print()

    print(f"DONE. {len(equipment_seen)} equipment types, {total_pmcs:,} PMCS rows, {total_parts:,} parts rows.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run extraction on a single test PDF**

```bash
python3 -c "
from ingest.extract import extract_pdf
from pathlib import Path
# Test on the smallest digital PDF
pdf = Path('TMs/TM 11-5820-890-10-HR.pdf')  # SINCGARS hand receipt, 3.4MB
result = extract_pdf(pdf, 'test-sincgars', 'TM 11-5820-890-10-HR')
print(f'Text: {len(result[\"full_text\"])} chars')
print(f'PMCS rows: {len(result[\"pmcs_rows\"])}')
print(f'Parts rows: {len(result[\"parts_rows\"])}')
# Show first 3 rows
for r in result['pmcs_rows'][:3]:
    print(f'  Item #{r[\"item_number\"]}: {r[\"item_to_inspect\"][:60]}')
"
```

Expected: text extracted, some PMCS rows identified. May find zero PMCS rows on hand receipt PDFs (which are COEI/BII lists, not PMCS tables). That's fine — the parts table should still catch them.

- [ ] **Step 5: Commit**

```bash
git add ingest/
git commit -m "feat: add PDF extraction and batch ingest pipeline"
```

---

### Task 6: Equipment List for Image Sourcing

**Files:**
- Create: `ingest/equipment_csv.py`

- [ ] **Step 1: Write ingest/equipment_csv.py**

```python
"""Generate equipment.csv from the database for image sourcing.

Usage:
    python -m ingest.equipment_csv

Output:
    equipment.csv — columns: id, name, tm_number, image_url (empty, to fill in)
"""
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from supabase import create_client


def main():
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")

    if not url or not key:
        print("ERROR: Set SUPABASE_URL and SUPABASE_KEY in .env")
        sys.exit(1)

    client = create_client(url, key)
    result = client.table("equipment").select("id,name,tm_number,image_url").order("name").execute()

    out_path = Path("equipment.csv")
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "name", "tm_number", "image_url"])
        writer.writeheader()
        for row in result.data:
            writer.writerow({
                "id": row["id"],
                "name": row["name"],
                "tm_number": row.get("tm_number", ""),
                "image_url": row.get("image_url", "") or "",
            })

    print(f"Wrote {len(result.data)} equipment rows to {out_path}")
    print("Fill in the image_url column after uploading images to Supabase Storage.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Generate equipment.csv**

```bash
# After running load_all.py to populate the database:
python -m ingest.equipment_csv
```

Verify `equipment.csv` exists and has the right columns. The `image_url` column will be empty — ready for the Hermes agent to fill in.

- [ ] **Step 3: Commit**

```bash
git add ingest/equipment_csv.py equipment.csv
git commit -m "feat: add equipment CSV generator for image sourcing"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** Each requirement has a task — schema (Task 1), app + API (Task 2), UI (Task 3), search E2E (Task 4), extraction + ingest (Task 5), equipment list (Task 6). Hosting/deploy kept as manual step per BUILD-PLAN.
- [x] **No placeholders:** Every step has real code or exact commands. No TBDs, no "add error handling here" notes.
- [x] **Type consistency:** `equipment_id` is `text` everywhere. `search_equipment` function signature matches `db.search()` call. Template variable names match route context dicts.
- [x] **File boundaries:** `db.py` owns all Supabase calls. `main.py` owns routing only. Templates are pure presentation. Ingest scripts are independent of the app.
