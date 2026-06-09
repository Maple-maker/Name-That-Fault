"""Batch ingest: walk the TMs/ directory, extract every PDF, load into Supabase.

Usage:
    python -m ingest.load_all

Requires:
    - .env with SUPABASE_URL and SUPABASE_SERVICE_KEY
    - PDFs in TMs/ directory
"""
import os
import re
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
    name = Path(pdf_name).stem
    # Try to extract the equipment name from parentheses (handle nested)
    start = None
    depth = 0
    for i, ch in enumerate(name):
        if ch == '(':
            if depth == 0:
                start = i
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0 and start is not None:
                return name[start + 1 : i].lower().replace(" ", "-").replace("/", "-")
    # Fallback: use the first part of the TM number
    tm_match = re.search(r'TM\s+([\d-]+)', name)
    if tm_match:
        return f"tm-{tm_match.group(1)}"
    # Last resort: slugify the filename
    return name.lower().replace(" ", "-")[:50]


def derive_equipment_name(pdf_name: str) -> str:
    """Derive a human-readable equipment name from the PDF filename."""
    name = Path(pdf_name).stem
    # Try parenthetical content (handle nested parens)
    start = None
    depth = 0
    for i, ch in enumerate(name):
        if ch == '(':
            if depth == 0:
                start = i
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0 and start is not None:
                return name[start + 1 : i].strip()
    # Fallback: remove TM prefix and return
    cleaned = re.sub(r'^TM\s+[\d-]+[\s,]*', '', name).strip()
    cleaned = re.sub(r'\s+\d{4}$', '', cleaned).strip()
    return cleaned or name


def derive_tm_number(pdf_name: str) -> str:
    """Extract TM number from PDF filename."""
    tm_match = re.search(r'(TM\s+[\d-]+)', pdf_name)
    if tm_match:
        return tm_match.group(1)
    return pdf_name


def main():
    from dotenv import load_dotenv
    load_dotenv()
    print("Starting ingest...", flush=True)

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
