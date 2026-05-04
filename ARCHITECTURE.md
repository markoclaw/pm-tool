# PM Tool Architecture

## Overview

PM Tool is an **AI-native project management system** for consulting firms. You drop in project documents (PDFs, Excel, Word), an LLM extracts structured data, and an MCP server exposes everything so an AI assistant can query your projects.

```
                    ┌───────────────────────┐
                    │     AI Assistant       │
                    │  (Claude, ChatGPT,     │
                    │   OpenClaw, etc.)      │
                    └───────────┬───────────┘
                                │ MCP protocol
                    ┌───────────▼───────────┐
                    │    server.py          │
                    │    (FastMCP)          │
                    │    17 tools           │
                    └─────┬───────┬─────────┘
                          │       │
              ┌───────────▼─┐  ┌──▼──────────┐
              │  parser.py  │  │   db.py      │
              │  (doc/text) │  │  (SQLite)    │
              └─────┬───────┘  └──────────────┘
                    │
          ┌─────────┼─────────┐
          │         │         │
     ┌────▼──┐ ┌───▼──┐ ┌───▼────┐
     │  PDF  │ │Excel │ │  DOCX  │
     │pymupdf│ │pandas│ │python- │
     │       │ │      │ │docx    │
     └───────┘ └──────┘ └────────┘
```

## Component Map

### `server.py` — The MCP Server (Entry Point)

**What it does:** Exposes the project management system to AI via the Model Context Protocol. Runs on `http://localhost:8000/mcp`.

**Key facts:**
- Uses FastMCP with streamable HTTP transport
- Auto-loads LLM config from `.llm_config.json` on startup
- 17 MCP tools (see full list in README)
- JSON responses throughout

**Startup flow:**
1. Imports `db` → triggers `init_db()` → creates tables if missing
2. Imports `parser` → loads document parsing + LLM client
3. Checks for LLM config in: env var → `.llm_config.json` file
4. If API key found, calls `parser.configure_llm()`
5. Registers all 17 MCP tools
6. Starts uvicorn on port 8000

### `db.py` — SQLite Database Layer

**What it does:** All data persistence. Zero-config — creates `pm_data.db` automatically.

**Tables:**

| Table | Purpose | Key fields |
|-------|---------|------------|
| `projects` | Top-level project container | name, status, timestamps |
| `documents` | Ingested files (PDF/Excel/Word) | filename, content_text, parsed_data_json |
| `tasks` | Work items, supports subtasks | hours_allocated, employee_id, parent_task_id |
| `scope_items` | Scope/work breakdown | category, hours_estimated |
| `employees` | Team members | position, billing_rate |

**Key design decisions:**
- `tasks.parent_task_id` → subtasks (self-referencing FK)
- `tasks.employee_id` → links to employee for billing
- `tasks.billing_rate_override` → per-task rate (falls back to employee rate)
- `scope_items.hours_estimated` → separate from tasks (scope ≠ task)
- All deletes cascade (delete a project → all tasks/docs/scope go too)
- `get_project_budget()` — calculates total hours × rate per task and per employee

### `parser.py` — Document Ingestion + AI Extraction

**What it does:** Parses uploaded files into text, then uses an LLM to extract structured project data.

**Parsers (no LLM needed):**
```
PDF  → pymupdf4llm → markdown
XLSX → pandas       → table
CSV  → pandas       → table
DOCX → python-docx  → plain text
```

**LLM extraction flow:**
1. File parsed to text
2. Text sent to OpenRouter API with extraction prompt
3. LLM returns JSON: `{summary, scope_items, tasks, stakeholders, deadlines, budget_info}`
4. Falls back to simple text extraction if LLM fails or isn't configured

**LLM config:**
```json
// .llm_config.json (gitignored)
{
  "openrouter_api_key": "sk-or-v1-...",
  "model": "google/gemini-2.5-flash-lite"
}
```

Default model: `google/gemini-2.5-flash-lite` (~$0.10/M input tokens)

### `test_ci.py` — CI Smoke Tests

Runs on GitHub Actions on every push. Tests: project CRUD, employee CRUD, tasks with hours, subtasks, scope, budget calculation, parser.

## Data Flow: Document → Project

```
1. User drops file    → server.ingest_document(filepath, project_id)
2. parser.parse_file  → text content + file_type
3. parser.extract_    → LLM returns structured JSON
   structured_data      (scope_items, tasks, budget, etc.)
4. db.add_document    → stores file + parsed JSON
5. Auto-create        → scope items from LLM output
6. Auto-create        → tasks from LLM output
```

## Data Flow: Querying

```
1. AI calls          → server.query_project(project_id, question)
2. db.get_project_   → loads project + all docs + tasks + scope
   summary
3. Server returns    → full context dump (documents truncated to 3000 chars each)
4. AI reasons over   → answers the question
   context
```

## Budget Calculation

```
Per task:    hours_allocated × effective_rate
             where effective_rate = billing_rate_override ?? employee.billing_rate
Per employee: SUM(task hours) × employee.billing_rate
Total:       SUM(all task costs)
```

## CI/CD

GitHub Actions workflow (`.github/workflows/test.yml`):
- Triggers on push/PR to main
- Python 3.11 on Ubuntu
- Installs dependencies, runs `test_ci.py`
- Tests: project CRUD, employees, tasks with hours, subtasks, scope, budget, parser

## File Map

```
pm-tool/
├── server.py              ← MCP server (17 tools, entry point)
├── db.py                  ← SQLite database layer
├── parser.py              ← Document parsing + LLM extraction
├── test_ci.py             ← CI smoke tests
├── test_scope.xlsx        ← Sample scope spreadsheet
├── mockup.html            ← UI mockup
├── requirements.txt       ← Python dependencies
├── .mcp.json              ← MCP client config
├── .llm_config.json       ← LLM API key (gitignored)
├── .gitignore
├── README.md              ← User documentation
├── TODO.md                ← Task board
└── .github/workflows/
    └── test.yml           ← CI pipeline
```

## Extending

To add a new feature:
1. **Database** → Add table/column in `db.py` `init_db()`
2. **CRUD** → Add functions in `db.py`
3. **Tool** → Add `@mcp.tool()` decorated function in `server.py`
4. **Test** → Add test case in `test_ci.py`

## Security Notes

- `.llm_config.json` contains the OpenRouter API key — **never commit**
- API keys should use OpenRouter usage limits to prevent cost overruns
- GitHub PAT stored with limited scope (repo, project, workflow)
- The MCP server runs on localhost only — no external exposure
