"""Extract text and table rows from a digital PDF."""
from pathlib import Path
import pdfplumber
import fitz  # PyMuPDF


def extract_full_text(pdf_path: Path) -> str:
    """Extract all text from a PDF using PyMuPDF (fast, works on most digital PDFs)."""
    doc = fitz.open(str(pdf_path))
    pages = []
    for page in doc:
        text = page.get_text()
        if text.strip():
            pages.append(text.strip())
    doc.close()
    return "\n\n".join(pages)


def extract_tables(pdf_path: Path) -> list[list[list[str]]]:
    """Extract all tables from a PDF using pdfplumber."""
    tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_tables = page.extract_tables()
            for tbl in page_tables:
                if tbl and len(tbl) > 1:  # skip empty/single-row tables
                    tables.append(tbl)
    return tables


def classify_table(table: list[list[str]]) -> str | None:
    """Guess if a table is PMCS, parts, or unknown based on column headers.

    Returns 'pmcs', 'parts', or None.
    """
    if not table or not table[0]:
        return None
    headers = " ".join(str(c).lower() for c in table[0] if c)

    pmcs_markers = ["item", "interval", "inspect", "not fully mission capable", "status"]
    parts_markers = ["nsn", "part number", "nomenclature", "niin", "rpstl"]

    pmcs_score = sum(1 for m in pmcs_markers if m in headers)
    parts_score = sum(1 for m in parts_markers if m in headers)

    if pmcs_score >= 2:
        return "pmcs"
    if parts_score >= 2:
        return "parts"
    return None


def table_to_rows(table: list[list[str]], table_type: str, equipment_id: str,
                  tm_number: str, pdf_name: str) -> list[dict]:
    """Convert a classified table to clean dict rows ready for the database."""
    rows = []
    headers = [str(h).strip().lower() if h else "" for h in table[0]]

    for row in table[1:]:
        if not row or all(not c or not str(c).strip() for c in row):
            continue
        cells = [str(c).strip() if c else "" for c in row]

        if table_type == "pmcs":
            rows.append({
                "equipment_id": equipment_id,
                "item_number": cells[0] if len(cells) > 0 else "",
                "inspection_interval": cells[1] if len(cells) > 1 else "",
                "item_to_inspect": cells[2] if len(cells) > 2 else "",
                "technical_status": cells[3] if len(cells) > 3 else "",
                "nsn": cells[4] if len(cells) > 4 else "",
                "tm_ref": f"{tm_number} — {pdf_name}",
            })
        elif table_type == "parts":
            rows.append({
                "equipment_id": equipment_id,
                "nsn": cells[0] if len(cells) > 0 else "",
                "part_number": cells[1] if len(cells) > 1 else "",
                "nomenclature": cells[2] if len(cells) > 2 else "",
                "source_tm": tm_number,
                "page_ref": "",
            })

    return rows


def extract_pdf(pdf_path: Path, equipment_id: str, tm_number: str) -> dict:
    """Extract everything from a single PDF.

    Returns:
        {
            "pdf_name": str,
            "full_text": str,
            "pmcs_rows": list[dict],
            "parts_rows": list[dict],
        }
    """
    pdf_name = pdf_path.name
    print(f"  Extracting: {pdf_name} ...")

    full_text = extract_full_text(pdf_path)
    tables = extract_tables(pdf_path)

    pmcs_rows = []
    parts_rows = []

    for tbl in tables:
        tbl_type = classify_table(tbl)
        if tbl_type == "pmcs":
            pmcs_rows.extend(table_to_rows(tbl, "pmcs", equipment_id, tm_number, pdf_name))
        elif tbl_type == "parts":
            parts_rows.extend(table_to_rows(tbl, "parts", equipment_id, tm_number, pdf_name))

    print(f"    → {len(full_text):,} chars text, {len(pmcs_rows)} PMCS rows, {len(parts_rows)} parts rows")

    return {
        "pdf_name": pdf_name,
        "full_text": full_text,
        "pmcs_rows": pmcs_rows,
        "parts_rows": parts_rows,
    }
