# TM Parts Finder — Maintenance Copilot Design

**Date:** 2026-06-09
**Status:** Approved

## Overview

A searchable database of Army Technical Manuals for operators conducting PMCS. An operator selects their equipment, describes a symptom in their own words, and gets back the PMCS item number, technical status, NSN, and TM reference — so they can identify faults and order parts fast.

**Primary user:** Operators performing before/during/after PMCS checks on equipment. Motor pool environment, NIPR-connected, any device with a browser.

**Out of scope:** DA 5988 form generation (handled through G-Army), offline support, CUI/export-controlled manuals.

---

## Architecture

```
Browser (any device, NIPR-net)
        │
        ▼
   FastAPI (Railway)
   ├── GET /search?equip={id}&q={query}
   ├── GET /equipment
   └── GET /item/{id}
        │
        ▼
   Supabase (Postgres)
   ├── equipment table
   ├── pmcs_items table
   ├── parts table
   └── full-text search (tsvector + pg_trgm)
```

**Stack unchanged from scaffold:** FastAPI + Supabase + Railway. Server-rendered HTML (Jinja2) for the web UI.

---

## Data Model

### `equipment`
The equipment selector. One row per unique equipment/vehicle type.

| Column | Type | Example |
|--------|------|---------|
| `id` | text (PK) | `hmmwv-m1151` |
| `name` | text | `HMMWV M1151` |
| `nomenclature` | text | `Truck, Utility, Armored` |
| `image_url` | text (nullable) | `https://...supabase.co/storage/...` |
| `tm_number` | text | `TM 9-2320-280-10` |

### `pmcs_items`
PMCS table rows extracted from operator-level TMs.

| Column | Type | Example |
|--------|------|---------|
| `id` | uuid (PK) | auto |
| `equipment_id` | text (FK → equipment) | `hmmwv-m1151` |
| `item_number` | text | `23` |
| `interval` | text | `Before` |
| `item_to_inspect` | text | `Engine Start` |
| `technical_status` | text | `Engine fails to crank — starter motor inoperative` |
| `nsn` | text (nullable) | `2920-01-234-5678` |
| `tm_ref` | text | `TM 9-2320-280-10, Page 2-47` |
| `search_vector` | tsvector | *(generated from all text columns)* |

### `parts`
Parts listings from RPSTL (-13P, -24P) manuals.

| Column | Type | Example |
|--------|------|---------|
| `id` | uuid (PK) | auto |
| `equipment_id` | text (FK → equipment) | `hmmwv-m1151` |
| `nsn` | text | `5331-01-234-5678` |
| `part_number` | text (nullable) | `M83521/2-022` |
| `nomenclature` | text | `O-RING` |
| `source_tm` | text | `TM 9-2320-280-24P` |
| `page_ref` | text (nullable) | `Page 4-12` |

### Indexes
- GIN index on `pmcs_items.search_vector` for full-text search
- Trigram index (`pg_trgm`) on `item_to_inspect`, `nomenclature` for fuzzy/partial matching
- B-tree index on `equipment_id` on all tables

---

## Extraction Pipeline

### Inventory
- **114 PDFs** (~62,000 pages) — 95.6% of pages are digital text
- **1 PDF** (HMMWV M1151 PMCS, 132 pages) — 131/132 pages are scanned images

### Path 1: Digital PDFs (113 PDFs, ~59,000 text pages)
```
PDF → pdfplumber extracts text/tables → classify rows → insert into DB
```
- PMCS tables identified by column signature (item number, interval columns)
- Parts tables identified by NSN/part number columns
- Non-table text extracted as searchable content blocks
- Batch script: `python -m ingest.load_all`

### Path 2: Scanned HMMWV PMCS (1 PDF, 131 image pages)
```
PDF → ocrmypdf → searchable PDF → pdfplumber extracts text → manual curation
```
- OCR enables text search but table structure may be imperfect
- PMCS rows hand-curated into a CSV, then loaded via ingest script
- Acceptable one-time cost for a single manual

### Path 3: Full-text only
```
PDF → PyMuPDF extracts all text → stored as searchable blocks
```
- Powers fuzzy search for content that isn't in structured tables
- Narrative descriptions, troubleshooting steps, fault conditions

### Equipment List Output
During extraction, the script writes `equipment.csv` with every unique equipment name and TM reference found. This list is used to:
1. Populate the `equipment` table
2. Identify which images need to be sourced for the dashboard

---

## Search

### Entry Point
```
GET /search?equip={equipment_id}&q={free-text query}
```

All results scoped to the selected equipment.

### Search Layers
1. **Full-text search** — Postgres `tsquery` / `tsvector` on all text columns. Handles natural language ("engine smokes when starting").
2. **Trigram similarity** — `pg_trgm` catches partial matches ("alt" → alternator) and misspellings ("altenator" → alternator).
3. **Equipment-scoped** — Every query filtered by `equipment_id`, enforced at the database level.

### Response Format
```json
[
  {
    "item_number": "23",
    "interval": "Before",
    "item_to_inspect": "Engine Start",
    "technical_status": "Engine fails to crank — starter motor inoperative",
    "nsn": "2920-01-234-5678",
    "tm_ref": "TM 9-2320-280-10, Page 2-47",
    "source": "pmcs",
    "relevance": 0.92
  }
]
```

Results ranked by relevance. Mixed results from `pmcs_items` and `parts` tables.

---

## Web UI

Three screens, server-rendered Jinja2 templates, dark AEGIS theme:

### 1. Equipment Selector
- Card grid: image + equipment name + TM number
- Click/tap selects equipment, advances to search
- Equipment images hosted in Supabase Storage, URL stored in `equipment.image_url`

### 2. Search
- Search bar with placeholder text: "Describe the symptom or part..."
- Results list below: item #, nomenclature, NSN, technical status, TM ref
- Each result links to detail view
- "Not what you're looking for?" — refine search or browse PMCS table

### 3. Item Detail
- Full PMCS item view: all fields from `pmcs_items`
- Copy button for NSN and technical status
- Back link to search results

### Responsive
Works on phones (primary use case), tablets, and laptops. No framework dependency — CSS Grid + Flexbox.

---

## Images for Equipment Dashboard

Supabase Storage bucket (`equipment-images`), public URLs stored in `equipment.image_url`.

### Workflow for Image Sourcing
1. Extraction script outputs `equipment.csv` — list of every equipment name found
2. Images sourced from DVIDS, Wikimedia Commons, or Army.mil (public release only)
3. Images uploaded to Supabase Storage dashboard
4. Public URL written to `equipment.image_url`

### Image Requirements
- Format: JPEG or PNG
- Recommended: 400×300px, under 200KB
- Subject: recognizable photo of the equipment

---

## Security

- Distribution A (public release) content only
- No CUI, export-controlled (B–F), or ITAR/EAR content
- Supabase anon key only in deployed app
- Supabase service_role key local only, never committed or deployed

---

## Out of Scope

- DA 5988 / DA 2404 form generation (G-Army handles this)
- Offline support (NIPR-connected motor pool only)
- Claude Vision API extraction (digital text extraction only, OCR for scanned pages)
- User authentication (single tool, shared access within motor pool)
- Semantic/vector search (full-text is sufficient; revisit if limiting)

---

## References

- [BUILD-PLAN.md](/BUILD-PLAN.md) — original scaffold plan
- [README.md](/README.md) — project overview and quickstart
- TMs directory: `/TMs/` — 114 PDFs, 62,247 pages
- DA 5988 reference: `/da5988.pdf`
