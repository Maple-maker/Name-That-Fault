"""Load extracted rows into Supabase."""
import os
from dotenv import load_dotenv
from supabase import create_client, ClientOptions

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

_client = None


def get_client():
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise RuntimeError("Set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env")
        _client = create_client(
            SUPABASE_URL,
            SUPABASE_SERVICE_KEY,
            options=ClientOptions(postgrest_client_timeout=120),
        )
    return _client


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
