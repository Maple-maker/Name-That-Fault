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
