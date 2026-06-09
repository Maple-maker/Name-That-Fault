"""Supabase client and query functions — single interface to the database."""
from app import config

_client = None  # Lazy-imported to allow app boot without supabase installed


def get_client():
    """Lazy-load Supabase client so the app boots before credentials exist."""
    global _client
    if _client is None:
        if not config.DATABASE_CONNECTED:
            raise RuntimeError("Supabase not configured. Set SUPABASE_URL and SUPABASE_KEY.")
        from supabase import create_client  # Lazy import
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
