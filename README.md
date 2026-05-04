# PM Tool — AI-Native Project Management for Consulting

Simple, database-backed project management with MCP server integration for AI access. Built for consulting/engineering firms — drop in documents, get projects, tasks, employees, hours, and budget tracking.

## What it does

1. **Ingest documents** — Drop in PDFs, Excel files, Word docs with project info (scopes of work, budgets, timelines)
2. **AI auto-extract** — LLM parses content and structures it into projects, tasks, scope items, and budget data
3. **Team & billing** — Employees with positions and billing rates, hours allocated per task/subtask
4. **Budget tracking** — Real-time cost rollup by task, employee, and project
5. **AI query** — MCP server exposes everything so an AI can answer questions about your projects
6. **Dashboard** — Project overview with task breakdown, budget, and team summaries

## Architecture

```
Excel/PDF/DOCX  →  parser.py  →  LLM extract  →  db.py (SQLite)  ←  server.py (MCP)  →  AI client
```

## Quick Start

```bash
pip install -r requirements.txt
python server.py
```

Then connect any MCP client to `http://localhost:8000/mcp`

## LLM Extraction (optional but recommended)

The tool auto-loads an OpenRouter API key from `.llm_config.json` or `OPENROUTER_API_KEY` env var. With LLM enabled, ingested documents get intelligent extraction: scope items with proper categories, tasks with priorities, stakeholders, deadlines, and budget info.

```json
// .llm_config.json
{
  "openrouter_api_key": "sk-or-v1-...",
  "model": "google/gemini-2.5-flash-lite"
}
```

Default model is `google/gemini-2.5-flash-lite` — very cheap (~$0.10/M input) and good enough for extraction.

## MCP Tools (17 total)

### Projects
- `create_project` / `list_projects` / `get_project` / `update_project` / `delete_project`

### Documents
- `ingest_document` — Parse and store PDF, Excel, CSV, DOCX (auto-extracts with LLM if enabled)
- `list_documents` / `get_document` / `search_documents`

### Tasks & Subtasks
- `create_task` — With hours_allocated, employee_id, parent_task_id
- `list_tasks` — Filter by status, list subtasks of any task
- `update_task` — Update status, hours, assign employee, override billing rate

### Scope
- `add_scope_item` / `list_scope`

### Team
- `add_employee` — Name, position, billing rate, email
- `list_employees` / `update_employee`

### Budget
- `project_budget` — Full cost breakdown: per-task, per-employee, total hours and cost
- `project_dashboard` — Visual overview

### AI Brain
- `query_project` — Natural language question about a project, returns full context
- `configure_llm` — Set/update API key and model
