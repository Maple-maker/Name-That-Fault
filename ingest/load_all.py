"""Batch ingest: walk the TMs/ directory, extract every PDF, load into Supabase.

Usage:
    python -m ingest.load_all

Requires:
    - .env with SUPABASE_URL and SUPABASE_SERVICE_KEY
    - PDFs in TMs/ directory

Safe to re-run — skips already-processed PDFs (tracked in ingest_checkpoint.txt).
"""
import os
import re
import sys
import traceback
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.extract import extract_pdf
from ingest.load import load_equipment, load_pmcs_items, load_parts


def derive_equipment_id(pdf_name: str) -> str:
    """Derive a stable equipment ID from the PDF filename."""
    name = Path(pdf_name).stem
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
    tm_match = re.search(r'TM\s+([\d-]+)', name)
    if tm_match:
        return f"tm-{tm_match.group(1)}"
    return name.lower().replace(" ", "-")[:50]


def derive_equipment_name(pdf_name: str) -> str:
    """Derive a human-readable equipment name from the PDF filename."""
    name = Path(pdf_name).stem
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
    cleaned = re.sub(r'^TM\s+[\d-]+[\s,]*', '', name).strip()
    cleaned = re.sub(r'\s+\d{4}$', '', cleaned).strip()
    return cleaned or name


def derive_tm_number(pdf_name: str) -> str:
    """Extract TM number from PDF filename."""
    tm_match = re.search(r'(TM\s+[\d-]+)', pdf_name)
    if tm_match:
        return tm_match.group(1)
    return pdf_name


def load_checkpoint() -> set:
    """Read set of already-processed PDF names."""
    path = Path("ingest_checkpoint.txt")
    if path.exists():
        return set(path.read_text().strip().splitlines())
    return set()


def save_checkpoint(pdf_name: str):
    """Append a completed PDF to the checkpoint file."""
    with open("ingest_checkpoint.txt", "a") as f:
        f.write(pdf_name + "\n")


def main():
    from dotenv import load_dotenv
    load_dotenv()
    print("Starting ingest...", flush=True)

    tms_dir = Path("TMs")
    if not tms_dir.exists():
        print("ERROR: TMs/ directory not found.")
        sys.exit(1)

    done = load_checkpoint()
    if done:
        print(f"Resuming: {len(done)} PDFs already processed, will skip them.\n")

    pdfs = sorted(tms_dir.glob("*.pdf"))
    remaining = [p for p in pdfs if p.name not in done]
    print(f"Found {len(pdfs)} PDFs total, {len(remaining)} remaining to process.\n")

    total_pmcs = 0
    total_parts = 0
    equipment_seen = set()
    failed = []

    for idx, pdf_path in enumerate(remaining, 1):
        equip_id = derive_equipment_id(pdf_path.name)
        equip_name = derive_equipment_name(pdf_path.name)
        tm_number = derive_tm_number(pdf_path.name)

        print(f"[{idx}/{len(remaining)}] {pdf_path.name}", flush=True)

        try:
            # Load equipment row (deduplicate)
            if equip_id not in equipment_seen:
                try:
                    load_equipment([{
                        "id": equip_id,
                        "name": equip_name,
                        "nomenclature": "",
                        "tm_number": tm_number,
                    }])
                    equipment_seen.add(equip_id)
                    print(f"  + Equipment: {equip_name}", flush=True)
                except Exception as e:
                    print(f"  ⚠ Equipment upsert failed: {e}", flush=True)

            # Extract
            result = extract_pdf(pdf_path, equip_id, tm_number)

            # Load
            if result["pmcs_rows"]:
                n = load_pmcs_items(result["pmcs_rows"])
                total_pmcs += n
                print(f"  → {n} PMCS rows loaded", flush=True)

            if result["parts_rows"]:
                n = load_parts(result["parts_rows"])
                total_parts += n
                print(f"  → {n} parts rows loaded", flush=True)

            save_checkpoint(pdf_path.name)

        except Exception as e:
            print(f"  ✗ FAILED: {e}", flush=True)
            failed.append(pdf_path.name)
            # Save checkpoint anyway so we don't retry the same broken PDF
            save_checkpoint(pdf_path.name)

    print(f"\nDONE. {len(equipment_seen)} equipment types, {total_pmcs:,} PMCS rows, {total_parts:,} parts rows.")
    if failed:
        print(f"FAILED ({len(failed)}): {', '.join(failed)}")


if __name__ == "__main__":
    main()
