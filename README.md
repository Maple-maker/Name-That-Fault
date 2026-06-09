# TM Parts Finder

Searchable database of Army Technical Manuals (**Distribution A / public release only**).
Type a fault or a part — get the NSN, the source TM, and the page so you can verify
and order the right part.

Part of the AEGIS system. Stack: **FastAPI** (app) · **Supabase** (Postgres +
full-text search) · **Railway** (hosting).

## Quickstart (local)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in your Supabase values when you have them
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. Before Supabase is connected you'll see a
"Database not connected" banner — that's expected. The app runs; the data comes next.

## Setup order

1. **Push to GitHub** (this repo runs and deploys fine before any backend exists).
2. **Create a Supabase project** and run `schema.sql` in its SQL editor.
   Optionally run `seed.sql` to load example rows and test search right away.
3. **Add credentials** to `.env`: `SUPABASE_URL` and `SUPABASE_KEY` (the *anon* key).
4. **Ingest manuals:** `python -m ingest.extract data/manual.pdf`, clean the CSV
   it produces, then `python -m ingest.load out/manual_parts.csv`.
5. **Deploy to Railway** from this repo.

Full walkthrough with commands: **[BUILD-PLAN.md](BUILD-PLAN.md)**.

## Keys

- `SUPABASE_KEY` = **anon** key. Powers the read-only app. Safe to deploy.
- `SUPABASE_SERVICE_KEY` = **service_role** key. For ingest only. Keep it local,
  never commit it, never put it in Railway.

## Security

Distribution A (public release) content only. Do **not** load CUI,
export-controlled, or restricted-distribution (B–F) manuals into this system.
