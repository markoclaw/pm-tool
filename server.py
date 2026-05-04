"""PM Tool MCP Server — Simple AI-connected project management.

Exposes tools for:
- Project CRUD
- Document ingestion (PDF, Excel, Word)
- Task management
- Querying across projects
"""

import json
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

import db
import parser as doc_parser

# Configure LLM from environment or file
_openrouter_key = os.environ.get("OPENROUTER_API_KEY")

# Configure LLM from config file, env, or tool
LLM_CONFIG_PATH = Path(__file__).parent / ".llm_config.json"
_openrouter_key = os.environ.get("OPENROUTER_API_KEY")
_llm_model = None

if not _openrouter_key and LLM_CONFIG_PATH.exists():
    try:
        with open(LLM_CONFIG_PATH) as f:
            llm_cfg = json.load(f)
            _openrouter_key = llm_cfg.get("openrouter_api_key")
            _llm_model = llm_cfg.get("model")
    except Exception:
        pass

if _openrouter_key:
    kwargs = {"api_key": _openrouter_key}
    if _llm_model:
        kwargs["model"] = _llm_model
    doc_parser.configure_llm(**kwargs)
    print(f"[pm-tool] LLM extraction enabled (model: {doc_parser._LLM_CONFIG['model']})", file=sys.stderr)

mcp = FastMCP("PM Tool", json_response=True)

# ============================================================
# Project Tools
# ============================================================

@mcp.tool()
def create_project(name: str, description: str = "") -> str:
    """Create a new project."""
    project = db.create_project(name, description)
    return json.dumps(project, indent=2)


@mcp.tool()
def list_projects(status: str = "") -> str:
    """List all projects. Optionally filter by status (active, completed, archived)."""
    s = status if status else None
    projects = db.list_projects(s)
    if not projects:
        return "No projects found."
    lines = []
    for p in projects:
        lines.append(f"  [{p['id']}] {p['name']} — {p['status']} (updated: {p['updated_at'][:10]})")
    return "\n".join(lines)


@mcp.tool()
def get_project(project_id: int) -> str:
    """Get full project details including task counts and document stats."""
    summary = db.get_project_summary(project_id)
    if not summary:
        return f"Project {project_id} not found."
    p = summary["project"]
    ts = summary["task_summary"]
    return json.dumps({
        "id": p["id"],
        "name": p["name"],
        "description": p["description"],
        "status": p["status"],
        "created": p["created_at"][:10],
        "updated": p["updated_at"][:10],
        "tasks": ts,
        "total_documents": summary["total_documents"],
        "total_scope_items": summary["total_scope_items"],
    }, indent=2)


@mcp.tool()
def update_project(project_id: int, name: str = "", description: str = "", status: str = "") -> str:
    """Update project fields. Leave blank to keep existing values."""
    kwargs = {}
    if name:
        kwargs["name"] = name
    if description:
        kwargs["description"] = description
    if status:
        kwargs["status"] = status
    result = db.update_project(project_id, **kwargs)
    return json.dumps(result, indent=2) if result else f"Project {project_id} not found."


@mcp.tool()
def delete_project(project_id: int) -> str:
    """Delete a project and all its documents, tasks, and scope items."""
    ok = db.delete_project(project_id)
    return f"Project {project_id} deleted." if ok else f"Project {project_id} not found."


# ============================================================
# Document Tools
# ============================================================

@mcp.tool()
def ingest_document(project_id: int, filepath: str) -> str:
    """Parse and store a document (PDF, Excel, CSV, DOCX) into a project.
    
    The document text is extracted and stored for querying.
    Returns a summary of what was extracted.
    """
    path = Path(filepath)
    if not path.exists():
        return f"Error: File not found: {filepath}"

    try:
        content_text, file_type = doc_parser.parse_file(str(path))
    except ValueError as e:
        return str(e)

    # Extract structured data
    extracted = doc_parser.extract_structured_data(content_text, file_type)

    doc = db.add_document(
        project_id=project_id,
        filename=path.name,
        file_type=file_type,
        content_text=content_text,
        parsed_data=extracted,
    )

    # Auto-populate scope items if found
    scope_count = 0
    for item in extracted.get("scope_items", []):
        db.add_scope_item(
            project_id=project_id,
            description=item.get("description", ""),
            category=item.get("category", "general"),
            document_id=doc["id"],
        )
        scope_count += 1

    # Auto-create tasks if found
    task_count = 0
    for item in extracted.get("tasks", []):
        db.create_task(
            project_id=project_id,
            title=item.get("title", "Untitled task"),
            description=item.get("description", ""),
            priority=item.get("priority", "medium"),
            source_document_id=doc["id"],
        )
        task_count += 1

    return json.dumps({
        "document_id": doc["id"],
        "filename": path.name,
        "file_type": file_type,
        "content_length": len(content_text),
        "summary": extracted.get("summary", "")[:300],
        "scope_items_extracted": scope_count,
        "tasks_extracted": task_count,
        "preview": content_text[:500],
    }, indent=2)


@mcp.tool()
def list_documents(project_id: int) -> str:
    """List all documents in a project."""
    docs = db.list_documents(project_id)
    if not docs:
        return "No documents in this project."
    lines = []
    for d in docs:
        lines.append(f"  [{d['id']}] {d['filename']} ({d['file_type']}) — {d['created_at'][:10]}")
    return "\n".join(lines)


@mcp.tool()
def get_document(document_id: int) -> str:
    """Get the full extracted text of a document."""
    doc = db.get_document(document_id)
    if not doc:
        return f"Document {document_id} not found."
    return doc["content_text"]


@mcp.tool()
def search_documents(query: str, project_id: int = 0) -> str:
    """Search across documents for a keyword or phrase.
    Use project_id=0 to search all projects."""
    pid = project_id if project_id else None
    results = db.search_documents(query, pid)
    if not results:
        return f"No documents matching '{query}'."
    lines = [f"Found {len(results)} document(s) matching '{query}':"]
    for r in results:
        lines.append(f"  [{r['id']}] {r['filename']} (project {r['project_id']})")
    return "\n".join(lines)


# ============================================================
# Task Tools
# ============================================================

@mcp.tool()
def create_task(project_id: int, title: str, description: str = "",
                priority: str = "medium", due_date: str = "",
                assigned_to: str = "", hours_allocated: float = 0,
                employee_id: int = 0, parent_task_id: int = 0) -> str:
    """Create a new task in a project.
    Priority: low, medium, high, critical.
    Set hours_allocated and employee_id to track billing.
    Set parent_task_id to create a subtask."""
    task = db.create_task(
        project_id=project_id,
        title=title,
        description=description,
        priority=priority,
        due_date=due_date if due_date else None,
        assigned_to=assigned_to,
        hours_allocated=hours_allocated,
        employee_id=employee_id if employee_id else None,
        parent_task_id=parent_task_id if parent_task_id else None,
    )
    return json.dumps(task, indent=2)


@mcp.tool()
def list_tasks(project_id: int, status: str = "", parent_task_id: int = 0) -> str:
    """List tasks in a project. Optionally filter by status (todo, in_progress, done, blocked).
    Set parent_task_id to list subtasks of a specific task."""
    s = status if status else None
    ptid = parent_task_id if parent_task_id else None
    tasks = db.list_tasks(project_id, s, ptid)
    if not tasks:
        return "No tasks found."
    lines = [f"Tasks for project {project_id}:"]
    for t in tasks:
        emoji = {"todo": "⬜", "in_progress": "🔄", "done": "✅", "blocked": "🚫"}.get(t["status"], "❓")
        hrs = f" ({t.get('hours_allocated', 0) or 0}h)" if t.get("hours_allocated") else ""
        lines.append(f"  {emoji} [{t['id']}] [{t['priority']}] {t['title']} — {t['status']}{hrs}")
        if t["due_date"]:
            lines[-1] += f" (due: {t['due_date']})"
    return "\n".join(lines)


@mcp.tool()
def update_task(task_id: int, title: str = "", description: str = "",
                status: str = "", priority: str = "",
                due_date: str = "", assigned_to: str = "",
                hours_allocated: float = -1, employee_id: int = -1,
                billing_rate_override: float = -1) -> str:
    """Update a task. Leave fields blank/negative to keep existing values."""
    kwargs = {}
    if title: kwargs["title"] = title
    if description: kwargs["description"] = description
    if status: kwargs["status"] = status
    if priority: kwargs["priority"] = priority
    if due_date: kwargs["due_date"] = due_date
    if assigned_to: kwargs["assigned_to"] = assigned_to
    if hours_allocated >= 0: kwargs["hours_allocated"] = hours_allocated
    if employee_id >= 0: kwargs["employee_id"] = employee_id if employee_id > 0 else None
    if billing_rate_override >= 0: kwargs["billing_rate_override"] = billing_rate_override if billing_rate_override > 0 else None

    task = db.update_task(task_id, **kwargs)
    return json.dumps(task, indent=2) if task else f"Task {task_id} not found."


# ============================================================
# Scope Tools
# ============================================================

@mcp.tool()
def add_scope_item(project_id: int, description: str,
                   category: str = "general") -> str:
    """Add a scope/work item to a project.
    Category examples: design, construction, electrical, plumbing, materials, labor."""
    item = db.add_scope_item(project_id, description, category)
    return json.dumps(item, indent=2)


@mcp.tool()
def list_scope(project_id: int, category: str = "") -> str:
    """List all scope items for a project, optionally filtered by category."""
    cat = category if category else None
    items = db.list_scope_items(project_id, cat)
    if not items:
        return "No scope items found."
    by_cat = {}
    for item in items:
        c = item["category"]
        by_cat.setdefault(c, []).append(item)

    lines = []
    for cat_name, cat_items in sorted(by_cat.items()):
        lines.append(f"\n## {cat_name} ({len(cat_items)} items)")
        for item in cat_items:
            lines.append(f"  - {item['description'][:120]}")
    return "\n".join(lines)


# ============================================================
# Query Tool — the "AI brain" entry point
# ============================================================

@mcp.tool()
def query_project(project_id: int, question: str) -> str:
    """Ask a natural-language question about a project.
    
    Searches all documents, tasks, and scope items for relevant information
    and returns a comprehensive context dump for the AI to reason over.
    """
    summary = db.get_project_summary(project_id)
    if not summary:
        return f"Project {project_id} not found."

    project = summary["project"]
    docs = db.list_documents(project_id)
    tasks = db.list_tasks(project_id)
    scope = db.list_scope_items(project_id)

    # Build context
    ctx = [
        f"# Project: {project['name']}",
        f"Description: {project['description']}",
        f"Status: {project['status']}",
        f"",
        f"## Question",
        question,
        f"",
        f"## Documents ({len(docs)})",
    ]
    for d in docs:
        ctx.append(f"\n### {d['filename']} ({d['file_type']})")
        ctx.append(d["content_text"][:3000])

    ctx.append(f"\n## Tasks ({len(tasks)})")
    for t in tasks:
        ctx.append(f"- [{t['status']}] [{t['priority']}] {t['title']}: {t['description'][:200]}")

    ctx.append(f"\n## Scope Items ({len(scope)})")
    for s in scope:
        ctx.append(f"- [{s['category']}] {s['description'][:200]}")

    ctx.append(f"\n---\nUse this context to answer the question: **{question}**")
    
    return "\n".join(ctx)


@mcp.tool()
def project_dashboard(project_id: int) -> str:
    """Get a full dashboard view of a project — tasks by status, documents, scope breakdown."""
    summary = db.get_project_summary(project_id)
    if not summary:
        return f"Project {project_id} not found."

    p = summary["project"]
    tasks = db.list_tasks(project_id)
    scope = db.list_scope_items(project_id)

    lines = [
        f"╔══════════════════════════════════════╗",
        f"║  PROJECT: {p['name'][:32].ljust(32)}║",
        f"╠══════════════════════════════════════╣",
        f"║ Status: {p['status'].ljust(27)}║",
        f"║ Docs: {str(summary['total_documents']).ljust(29)}║",
        f"║ Scope Items: {str(summary['total_scope_items']).ljust(24)}║",
        f"╠══════════════════════════════════════╣",
    ]

    # Task breakdown
    statuses = {}
    for t in tasks:
        s = t["status"]
        statuses.setdefault(s, 0)
        statuses[s] += 1

    lines.append("║ TASKS:")
    for s, count in statuses.items():
        emoji = {"todo": "⬜", "in_progress": "🔄", "done": "✅", "blocked": "🚫"}.get(s, "❓")
        lines.append(f"║  {emoji} {s}: {count}")

    # Scope by category
    cats = {}
    for s in scope:
        c = s["category"]
        cats.setdefault(c, 0)
        cats[c] += 1
    if cats:
        lines.append("╠══════════════════════════════════════╣")
        lines.append("║ SCOPE BREAKDOWN:")
        for c, count in sorted(cats.items()):
            lines.append(f"║  {c}: {count}")

    lines.append("╚══════════════════════════════════════╝")
    return "\n".join(lines)


@mcp.tool()
def configure_llm(api_key: str = "", model: str = "") -> str:
    """Configure or update the LLM settings for document extraction.
    
    Provide an OpenRouter API key and optionally a model name.
    If no key provided, reads from OPENROUTER_API_KEY env var.
    
    Common cheap models:
    - google/gemini-2.5-flash-lite (default, cheapest)
    - meta-llama/llama-4-scout
    - deepseek/deepseek-chat
    """
    enabled = doc_parser.configure_llm(api_key=api_key if api_key else None, model=model if model else None)
    if enabled:
        # Persist to config
        cfg = {"openrouter_api_key": doc_parser._LLM_CONFIG["api_key"], "model": doc_parser._LLM_CONFIG["model"]}
        with open(LLM_CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
        return f"LLM enabled. Model: {doc_parser._LLM_CONFIG['model']}"
    return "LLM not configured — provide an api_key or set OPENROUTER_API_KEY."


# ============================================================
# Employee Tools
# ============================================================

@mcp.tool()
def add_employee(name: str, position: str = "", billing_rate: float = 0,
                 email: str = "") -> str:
    """Add an employee/contractor with their position and hourly billing rate.
    Position examples: Project Manager, Senior Engineer, Junior Designer, Surveyor."""
    emp = db.create_employee(name, position, billing_rate, email)
    return json.dumps(emp, indent=2)


@mcp.tool()
def list_employees() -> str:
    """List all employees with their positions and billing rates."""
    emps = db.list_employees()
    if not emps:
        return "No employees added yet. Use add_employee to add one."
    lines = ["Employees:"]
    for e in emps:
        lines.append(f"  [{e['id']}] {e['name']} — {e['position']} @ ${e['billing_rate']:.2f}/hr")
    return "\n".join(lines)


@mcp.tool()
def update_employee(employee_id: int, name: str = "", position: str = "",
                    billing_rate: float = -1, email: str = "") -> str:
    """Update an employee's details. Leave fields blank/negative to keep existing."""
    kwargs = {}
    if name: kwargs["name"] = name
    if position: kwargs["position"] = position
    if billing_rate >= 0: kwargs["billing_rate"] = billing_rate
    if email: kwargs["email"] = email
    emp = db.update_employee(employee_id, **kwargs)
    return json.dumps(emp, indent=2) if emp else f"Employee {employee_id} not found."


# ============================================================
# Budget Tools
# ============================================================

@mcp.tool()
def project_budget(project_id: int) -> str:
    """Get a full budget breakdown for a project.
    Shows total hours, total cost, per-task breakdown, and per-employee summary."""
    project = db.get_project(project_id)
    if not project:
        return f"Project {project_id} not found."
    budget = db.get_project_budget(project_id)

    lines = [
        f"╔══════════════════════════════════════════╗",
        f"║  BUDGET: {project['name'][:30].ljust(30)}║",
        f"╠══════════════════════════════════════════╣",
        f"║ Total Task Hours: {str(budget['total_task_hours']).ljust(19)}║",
        f"║ Total Task Cost:  ${str(f"{budget['total_task_cost']:,.2f}").ljust(18)}║",
        f"║ Scope Est. Hours: {str(budget['scope_hours_estimated']).ljust(19)}║",
    ]

    if budget["tasks"]:
        lines.append("╠══════════════════════════════════════════╣")
        lines.append("║ TASK BREAKDOWN:")
        for t in budget["tasks"]:
            name = t["title"][:22]
            lines.append(f"║  {name.ljust(22)} {str(t['hours']).rjust(5)}h @ ${t['rate']:.0f} = ${t['cost']:,.0f}")

    if budget["employees"]:
        lines.append("╠══════════════════════════════════════════╣")
        lines.append("║ EMPLOYEE SUMMARY:")
        for e in budget["employees"]:
            name = e["name"][:20]
            lines.append(f"║  {name.ljust(20)} {str(e['hours']).rjust(5)}h = ${e['cost']:,.0f}")

    lines.append("╚══════════════════════════════════════════╝")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
