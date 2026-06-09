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
