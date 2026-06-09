"""Scan TMs/ directory and generate equipment.csv from PDF filenames.

No database required — runs standalone in seconds.
Output: equipment.csv with columns id, name, tm_number, image_url (empty)
"""
import csv
import re
from pathlib import Path


def _extract_paren_content(s: str) -> str | None:
    """Extract content from the last (outermost) parenthesized group.

    Handles nested parens: '(AN_GRC-245(V)4)' → 'AN_GRC-245(V)4'
    """
    # Find all opening paren positions
    start = None
    depth = 0
    for i, ch in enumerate(s):
        if ch == '(':
            if depth == 0:
                start = i
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0 and start is not None:
                return s[start + 1 : i]
    return None


def derive_equipment_id(pdf_name: str) -> str:
    """Example: 'TM 9-2320-280-10 (HMMWV M1151) 2023.pdf' → 'hmmwv-m1151'"""
    name = Path(pdf_name).stem
    paren_content = _extract_paren_content(name)
    if paren_content:
        return paren_content.lower().replace(" ", "-").replace("/", "-")
    tm_match = re.search(r'TM\s+([\d-]+)', name)
    if tm_match:
        return f"tm-{tm_match.group(1)}"
    return name.lower().replace(" ", "-")[:50]


def derive_equipment_name(pdf_name: str) -> str:
    """Extract human-readable equipment name from filename."""
    name = Path(pdf_name).stem
    paren_content = _extract_paren_content(name)
    if paren_content:
        return paren_content.strip()
    # No parens: remove TM prefix, clean up
    cleaned = re.sub(r'^TM\s+[\d-]+[\s,]*', '', name).strip()
    # Remove trailing junk (years, stray chars)
    cleaned = re.sub(r'\s+\d{4}$', '', cleaned).strip()
    return cleaned or name


def derive_tm_number(pdf_name: str) -> str:
    """Extract TM number from filename."""
    tm_match = re.search(r'(TM\s+[\d-]+)', pdf_name)
    if tm_match:
        return tm_match.group(1)
    return pdf_name


def main():
    tms_dir = Path("TMs")
    if not tms_dir.exists():
        print("ERROR: TMs/ directory not found.")
        return

    pdfs = sorted(tms_dir.glob("*.pdf"))
    print(f"Scanning {len(pdfs)} PDFs in TMs/ ...\n")

    seen = {}
    for pdf_path in pdfs:
        equip_id = derive_equipment_id(pdf_path.name)
        if equip_id not in seen:
            seen[equip_id] = {
                "id": equip_id,
                "name": derive_equipment_name(pdf_path.name),
                "tm_number": derive_tm_number(pdf_path.name),
                "image_url": "",
            }

    out_path = Path("equipment.csv")
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "name", "tm_number", "image_url"])
        writer.writeheader()
        for row in sorted(seen.values(), key=lambda r: r["name"]):
            writer.writerow(row)

    print(f"Wrote {len(seen)} unique equipment types to {out_path}")
    print("\nFirst 10 entries:")
    for i, row in enumerate(sorted(seen.values(), key=lambda r: r["name"])):
        if i >= 10:
            break
        print(f"  {row['name']:50s}  ({row['id']:40s})  {row['tm_number']}")


if __name__ == "__main__":
    main()
