# TM Parts Finder — Build Plan

A searchable database of Army Technical Manuals. An operator types a fault or a
part and gets back the NSN, the source TM, and the page — so they can verify and
order the right part fast.

**Status:** scaffold complete, ready to push to GitHub. Supabase gets connected
*after* the first push, exactly as planned.

**Security:** confirmed **Distribution A (public release) only.** Cloud hosting
(Railway) and cloud services are therefore in scope. Never load a manual marked
B–F, CUI, or export-controlled (ITAR/EAR) into this system — that content stays
off commercial cloud entirely.

---

## Stack

- **Supabase** — Postgres database + Storage (for the source PDFs). Same setup you
  used for Asymmetry.
- **FastAPI** — the search API and the web page.
- **Railway** — hosts the FastAPI app; connects to Supabase over its keys.
- **pdfplumber** — pulls tables out of the PDFs during ingest.

---

## What's in the repo

```
tm-parts-finder/
├── app/
│   ├── main.py            FastAPI app + the search route
│   ├── config.py          reads settings from .env
│   ├── db.py              talks to Supabase (loads lazily, so the app boots
│   │                       fine before you've connected anything)
│   ├── templates/
│   │   └── index.html     the search page
│   └── static/
│       └── style.css      dark AEGIS theme
├── ingest/
│   ├── extract.py         PDF -> raw table rows (review before loading)
│   └── load.py            cleaned rows -> Supabase (run locally only)
├── schema.sql             core database: tables + full-text search
├── schema_semantic.sql    OPTIONAL: pgvector semantic search (add later)
├── seed.sql               OPTIONAL: example rows to test search
├── requirements.txt
├── .env.example           copy to .env and fill in
├── .gitignore             keeps .env and your PDFs out of git
├── Procfile               how Railway starts the app
└── README.md
```

---

## Order of operations

You wanted this on GitHub first, then Supabase. That's the order below.

### Step 1 — Push to GitHub (do this first)

From inside the unzipped folder:

```bash
git init
git add .
git commit -m "Initial scaffold: TM Parts Finder"
```

Create an empty repo on GitHub (no README — we have one), then:

```bash
git remote add origin https://github.com/YOUR-USERNAME/tm-parts-finder.git
git branch -M main
git push -u origin main
```

Your `.env` and your PDFs are gitignored, so nothing sensitive goes up.

### Step 2 — Run it locally to confirm it works

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. You'll see the search page with a "Database not
connected yet" banner — expected. The plumbing works; we connect the data next.

### Step 3 — Connect Supabase

1. Create a new project at supabase.com.
2. In the SQL editor, paste and run **schema.sql**.
   (Optional: also run **seed.sql** to load a few example rows so you can test
   search immediately.)
3. In **Project Settings → API**, copy three things: the **Project URL**, the
   **anon** key, and the **service_role** key.
4. Copy `.env.example` to `.env` and fill them in:
   - `SUPABASE_URL` and `SUPABASE_KEY` (the **anon** key) power the app.
   - `SUPABASE_SERVICE_KEY` (the **service_role** key) is for ingest only — keep
     it local, never commit or deploy it.
5. Restart the app. Search now returns results.

### Step 4 — Load your manuals

Put each PDF in `data/`, then:

```bash
python -m ingest.extract data/your_manual.pdf
```

This writes the raw table rows to `out/your_manual_rows.csv`. Open it — you'll
see the actual column layout of that manual's parts list. Map the columns to
`nsn`, `part_number`, `nomenclature`, `description`, `source_tm`, `page_ref`
(TM layouts differ, so this first pass is hands-on), save a cleaned CSV, then:

```bash
python -m ingest.load out/your_manual_parts.csv
```

> **Scanned PDFs.** If `extract.py` finds no tables, your PDF is images, not real
> text. Two options: (a) OCR it first with `ocrmypdf`, or (b) since these are
> public release, send page images to Claude's vision API and have it return
> clean structured rows. Tell me which and I'll write that path for you.

### Step 5 — Deploy to Railway

1. In Railway: **New Project → Deploy from GitHub repo →** pick this repo.
2. Add the same environment variables as your `.env` — but only the **anon** key,
   **not** the service key.
3. Railway reads the `Procfile` and starts the app, then gives you a public URL.

We'll confirm the exact Railway settings (build/start command, port) together
when you reach this step.

---

## The phases (the bigger picture)

1. **Extract** — PDF tables → structured rows. The make-or-break step. *(ingest/)*
2. **Store** — Postgres tables + full-text index. *(schema.sql)*
3. **Search** — full-text first (exact, fast, free). Semantic later. *(app/)*
4. **Web UI** — search box → results with NSN, TM, page. *(app/templates)*
5. **Deploy** — Railway. *(Procfile)*

---

## Open decisions

- **Are the PDFs digital text or scanned images?** Decides the extraction method
  in Step 4. We confirm this the moment you run `extract.py` on a real manual.
- **Semantic search yet?** Skip it until full-text feels limiting. When you want
  it, run `schema_semantic.sql` and we'll add the embedding step (cloud embeddings
  are fine here since it's all Distribution A).

---

## Next action

Push to GitHub (Step 1), then run it locally (Step 2) and tell me what you see.
