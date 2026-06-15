"""Read content from uploaded files — text, PDF, CSV, images."""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any


def read_file(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {"error": "File not found", "content": ""}

    suffix = path.suffix.lower()
    name = path.name

    # Plain text
    if suffix in (".txt", ".md", ".py", ".js", ".ts", ".html", ".css", ".json", ".yaml", ".yml", ".xml", ".toml", ".ini", ".cfg", ".log", ".sh", ".bat", ".ps1", ".sql", ".r", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".hpp"):
        try:
            text = path.read_text("utf-8", errors="replace")
            return {"type": "text", "name": name, "content": text, "size": len(text)}
        except Exception as e:
            return {"error": str(e), "content": ""}

    # PDF
    if suffix == ".pdf":
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(path))
            pages = []
            for page in doc:
                pages.append(page.get_text())
            text = "\n\n".join(pages)
            doc.close()
            return {"type": "pdf", "name": name, "content": text, "pages": len(pages), "size": len(text)}
        except ImportError:
            return {"error": "PDF support requires PyMuPDF: pip install PyMuPDF", "content": ""}
        except Exception as e:
            return {"error": str(e), "content": ""}

    # CSV
    if suffix == ".csv":
        try:
            text = path.read_text("utf-8", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)
            headers = reader.fieldnames or []
            preview = f"CSV: {len(rows)} rows, columns: {', '.join(headers)}\n"
            if rows:
                preview += "First 5 rows:\n"
                for i, row in enumerate(rows[:5]):
                    preview += f"  {json.dumps(row)}\n"
            return {"type": "csv", "name": name, "content": preview, "rows": len(rows), "headers": headers, "size": len(text)}
        except Exception as e:
            return {"error": str(e), "content": ""}

    # JSON
    if suffix == ".json":
        try:
            data = json.loads(path.read_text("utf-8", errors="replace"))
            formatted = json.dumps(data, indent=2)
            return {"type": "json", "name": name, "content": formatted, "size": len(formatted)}
        except Exception as e:
            return {"error": str(e), "content": ""}

    # Images — note the file for potential vision support
    if suffix in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
        size = path.stat().st_size
        return {"type": "image", "name": name, "content": f"[Image: {name} ({size} bytes)]", "size": size}

    # Unknown
    try:
        text = path.read_text("utf-8", errors="replace")
        return {"type": "text", "name": name, "content": text[:50000], "size": len(text)}
    except Exception:
        return {"type": "binary", "name": name, "content": f"[Binary file: {name} ({path.stat().st_size} bytes)]", "size": path.stat().st_size}


def get_type_label(result: dict[str, Any]) -> str:
    mapping = {
        "text": "Text file",
        "pdf": "PDF document",
        "csv": "CSV spreadsheet",
        "json": "JSON data",
        "image": "Image",
        "binary": "Binary file",
    }
    return mapping.get(result.get("type", ""), "File")
