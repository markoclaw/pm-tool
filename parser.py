"""Document parser: PDFs, Excel, Word → structured text."""

import json
import os
import urllib.request
import urllib.error
from pathlib import Path

# ---- LLM Client (OpenRouter) ----

_LLM_CONFIG = {
    "enabled": False,
    "api_key": None,
    "model": "google/gemini-2.5-flash-lite",
    "base_url": "https://openrouter.ai/api/v1/chat/completions",
}


def configure_llm(api_key: str = None, model: str = None):
    """Enable and configure the LLM extractor."""
    if api_key:
        _LLM_CONFIG["api_key"] = api_key
    elif not _LLM_CONFIG["api_key"]:
        _LLM_CONFIG["api_key"] = os.environ.get("OPENROUTER_API_KEY")
    if model:
        _LLM_CONFIG["model"] = model
    _LLM_CONFIG["enabled"] = bool(_LLM_CONFIG["api_key"])
    return _LLM_CONFIG["enabled"]


def _call_openrouter(system_prompt: str, user_prompt: str) -> str:
    """Send a chat completion request to OpenRouter. Returns the response text."""
    body = json.dumps({
        "model": _LLM_CONFIG["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 2048,
    }).encode("utf-8")

    req = urllib.request.Request(
        _LLM_CONFIG["base_url"],
        data=body,
        headers={
            "Authorization": f"Bearer {_LLM_CONFIG["api_key"]}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "PM Tool",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenRouter HTTP {e.code}: {body[:500]}") from e
    except Exception as e:
        raise RuntimeError(f"OpenRouter call failed: {e}") from e


def parse_pdf(filepath: str) -> str:
    """Parse a PDF into markdown-style text using pymupdf4llm."""
    import pymupdf4llm
    pages = pymupdf4llm.to_markdown(filepath)
    return pages if pages else "(empty or unreadable PDF)"


def parse_excel(filepath: str) -> str:
    """Parse Excel into structured JSON-like text."""
    import pandas as pd

    xl = pd.ExcelFile(filepath)
    parts = []
    for sheet in xl.sheet_names:
        df = pd.read_excel(filepath, sheet_name=sheet)
        # Convert to a readable table
        parts.append(f"## Sheet: {sheet}")
        parts.append(df.to_markdown(index=False) if not df.empty else "(empty sheet)")
    return "\n\n".join(parts)


def parse_docx(filepath: str) -> str:
    """Parse Word document to text."""
    from docx import Document
    doc = Document(filepath)
    return "\n".join(p.text for p in doc.paragraphs) or "(empty document)"


PARSERS = {
    ".pdf": parse_pdf,
    ".xlsx": parse_excel,
    ".xls": parse_excel,
    ".csv": parse_excel,  # pandas handles CSV too
    ".docx": parse_docx,
}


def parse_file(filepath: str) -> tuple[str, str]:
    """Parse a file and return (content_text, file_type)."""
    path = Path(filepath)
    ext = path.suffix.lower()

    if ext not in PARSERS:
        raise ValueError(f"Unsupported file type: {ext}. Supported: {list(PARSERS.keys())}")

    content = PARSERS[ext](str(path))
    return content, ext


def extract_structured_data(content_text: str, file_type: str) -> dict:
    """
    Extract structured project data from parsed content.
    
    Uses the configured LLM if available (via configure_llm),
    otherwise falls back to simple extraction.
    
    Returns a dict with keys: summary, key_items, detected_categories
    """
    if _LLM_CONFIG["enabled"]:
        return _llm_extract(content_text, file_type)
    return _simple_extract(content_text, file_type)


def _simple_extract(content_text: str, file_type: str) -> dict:
    """Basic extraction without LLM."""
    lines = [l.strip() for l in content_text.split("\n") if l.strip()]
    return {
        "summary": content_text[:500] if len(content_text) > 500 else content_text,
        "key_items": lines[:20],  # First 20 non-empty lines
        "detected_categories": [],
        "extraction_method": "basic",
    }


def _llm_extract(content_text: str, file_type: str) -> dict:
    """Use LLM to extract structured info from document content."""
    system = """You are a project management data extractor. Extract structured info from documents.
Return ONLY valid JSON with these keys:
- "summary": 2-3 sentence summary of the document
- "scope_items": list of scope/work items found (each with "description" and "category")
- "tasks": list of tasks found (each with "title", "description", "priority")
- "stakeholders": list of people/organizations mentioned
- "deadlines": list of dates/deadlines mentioned
- "budget_info": any budget/financial info found (string or null)

Categories for scope_items should be one of: design, construction, electrical, plumbing, 
materials, labor, permits, timeline, budget, general

If nothing relevant found for a key, use empty list or null."""
    
    prompt = f"""Extract project management data from this {file_type} document:

{content_text[:8000]}

Return the JSON:"""

    try:
        response = _call_openrouter(system, prompt)
        # Strip markdown code fences if present
        response = response.strip()
        if response.startswith("```"):
            response = response.split("\n", 1)[-1]
            if response.endswith("```"):
                response = response[:-3].strip()
        return json.loads(response)
    except Exception as e:
        print(f"LLM extraction failed ({e}), falling back to simple extraction", file=__import__('sys').stderr)
        return _simple_extract(content_text, file_type)
