"""Database layer for the PM tool. SQLite, zero config."""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "pm_data.db"


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            file_type TEXT NOT NULL,
            content_text TEXT DEFAULT '',
            parsed_data_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            position TEXT DEFAULT '',
            billing_rate REAL NOT NULL DEFAULT 0,
            email TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            parent_task_id INTEGER,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT DEFAULT 'todo',
            due_date TEXT,
            assigned_to TEXT DEFAULT '',
            employee_id INTEGER,
            priority TEXT DEFAULT 'medium',
            hours_allocated REAL DEFAULT 0,
            billing_rate_override REAL,
            source_document_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (parent_task_id) REFERENCES tasks(id) ON DELETE SET NULL,
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE SET NULL,
            FOREIGN KEY (source_document_id) REFERENCES documents(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS scope_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            document_id INTEGER,
            category TEXT DEFAULT 'general',
            description TEXT NOT NULL,
            hours_estimated REAL DEFAULT 0,
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_docs_project ON documents(project_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_employee ON tasks(employee_id);
        CREATE INDEX IF NOT EXISTS idx_scope_project ON scope_items(project_id);
    """)
    conn.commit()
    conn.close()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Projects ---

def create_project(name: str, description: str = "") -> dict:
    conn = get_db()
    ts = now()
    cur = conn.execute(
        "INSERT INTO projects (name, description, status, created_at, updated_at) VALUES (?, ?, 'active', ?, ?)",
        (name, description, ts, ts),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


def list_projects(status: str = None) -> list[dict]:
    conn = get_db()
    if status:
        rows = conn.execute("SELECT * FROM projects WHERE status = ? ORDER BY updated_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_project(project_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_project(project_id: int, **kwargs) -> dict | None:
    valid = {"name", "description", "status", "metadata_json"}
    updates = {k: v for k, v in kwargs.items() if k in valid}
    if not updates:
        return get_project(project_id)
    updates["updated_at"] = now()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [project_id]
    conn = get_db()
    conn.execute(f"UPDATE projects SET {set_clause} WHERE id = ?", values)
    conn.commit()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_project(project_id: int) -> bool:
    conn = get_db()
    cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


# --- Documents ---

def add_document(project_id: int, filename: str, file_type: str,
                 content_text: str = "", parsed_data: dict = None) -> dict:
    conn = get_db()
    ts = now()
    cur = conn.execute(
        "INSERT INTO documents (project_id, filename, file_type, content_text, parsed_data_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, filename, file_type, content_text, json.dumps(parsed_data or {}), ts),
    )
    # Touch project timestamp
    conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (ts, project_id))
    conn.commit()
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


def list_documents(project_id: int) -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM documents WHERE project_id = ? ORDER BY created_at DESC", (project_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_document(document_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def search_documents(query: str, project_id: int = None) -> list[dict]:
    conn = get_db()
    like = f"%{query}%"
    if project_id:
        rows = conn.execute(
            "SELECT * FROM documents WHERE project_id = ? AND (filename LIKE ? OR content_text LIKE ? OR parsed_data_json LIKE ?) ORDER BY created_at DESC",
            (project_id, like, like, like),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM documents WHERE filename LIKE ? OR content_text LIKE ? OR parsed_data_json LIKE ? ORDER BY created_at DESC",
            (like, like, like),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Tasks ---

def create_task(project_id: int, title: str, description: str = "",
                due_date: str = None, assigned_to: str = "",
                priority: str = "medium", source_document_id: int = None,
                employee_id: int = None, hours_allocated: float = 0,
                parent_task_id: int = None) -> dict:
    conn = get_db()
    ts = now()
    cur = conn.execute(
        """INSERT INTO tasks (project_id, title, description, status, due_date,
           assigned_to, priority, source_document_id, employee_id, hours_allocated,
           parent_task_id, created_at, updated_at)
           VALUES (?, ?, ?, 'todo', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (project_id, title, description, due_date, assigned_to, priority,
         source_document_id, employee_id, hours_allocated, parent_task_id, ts, ts),
    )
    conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (ts, project_id))
    conn.commit()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


def list_tasks(project_id: int, status: str = None, parent_task_id: int = None) -> list[dict]:
    conn = get_db()
    if parent_task_id is not None:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE project_id = ? AND parent_task_id = ? ORDER BY priority DESC, due_date ASC",
            (project_id, parent_task_id),
        ).fetchall()
    elif status:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE project_id = ? AND status = ? AND parent_task_id IS NULL ORDER BY priority DESC, due_date ASC",
            (project_id, status),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE project_id = ? AND parent_task_id IS NULL ORDER BY status, priority DESC, due_date ASC",
            (project_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_task(task_id: int, **kwargs) -> dict | None:
    valid = {"title", "description", "status", "due_date", "assigned_to",
             "priority", "employee_id", "hours_allocated", "billing_rate_override",
             "parent_task_id"}
    updates = {k: v for k, v in kwargs.items() if k in valid}
    if not updates:
        return None
    updates["updated_at"] = now()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [task_id]
    conn = get_db()
    conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
    conn.commit()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# --- Scope Items ---

def add_scope_item(project_id: int, description: str,
                   category: str = "general", document_id: int = None,
                   hours_estimated: float = 0, metadata: dict = None) -> dict:
    conn = get_db()
    ts = now()
    cur = conn.execute(
        "INSERT INTO scope_items (project_id, document_id, category, description, hours_estimated, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, document_id, category, description, hours_estimated, json.dumps(metadata or {}), ts),
    )
    conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (ts, project_id))
    conn.commit()
    row = conn.execute("SELECT * FROM scope_items WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


def list_scope_items(project_id: int, category: str = None) -> list[dict]:
    conn = get_db()
    if category:
        rows = conn.execute(
            "SELECT * FROM scope_items WHERE project_id = ? AND category = ? ORDER BY created_at DESC",
            (project_id, category),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM scope_items WHERE project_id = ? ORDER BY category, created_at DESC",
            (project_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Employees ---

def create_employee(name: str, position: str = "", billing_rate: float = 0,
                    email: str = "") -> dict:
    conn = get_db()
    ts = now()
    cur = conn.execute(
        "INSERT INTO employees (name, position, billing_rate, email, created_at) VALUES (?, ?, ?, ?, ?)",
        (name, position, billing_rate, email, ts),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM employees WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


def list_employees() -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM employees ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_employee(employee_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_employee(employee_id: int, **kwargs) -> dict | None:
    valid = {"name", "position", "billing_rate", "email"}
    updates = {k: v for k, v in kwargs.items() if k in valid}
    if not updates:
        return get_employee(employee_id)
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [employee_id]
    conn = get_db()
    conn.execute(f"UPDATE employees SET {set_clause} WHERE id = ?", values)
    conn.commit()
    row = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_employee(employee_id: int) -> bool:
    conn = get_db()
    cur = conn.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


# --- Budget helpers ---

def get_project_budget(project_id: int) -> dict:
    """Calculate total hours and cost for a project."""
    conn = get_db()
    conn.row_factory = sqlite3.Row

    # Tasks with employees
    task_rows = conn.execute("""
        SELECT t.id, t.title, t.hours_allocated, t.billing_rate_override,
               t.status, e.name as employee_name, e.billing_rate as employee_rate,
               e.position as employee_position
        FROM tasks t
        LEFT JOIN employees e ON t.employee_id = e.id
        WHERE t.project_id = ?
    """, (project_id,)).fetchall()

    total_task_hours = 0.0
    total_task_cost = 0.0
    task_details = []
    for t in task_rows:
        hours = t["hours_allocated"] or 0
        rate = t["billing_rate_override"] or t["employee_rate"] or 0
        cost = hours * rate
        total_task_hours += hours
        total_task_cost += cost
        task_details.append({
            "task_id": t["id"],
            "title": t["title"],
            "hours": hours,
            "rate": rate,
            "cost": round(cost, 2),
            "employee": t["employee_name"],
            "status": t["status"],
        })

    # Scope hours
    scope_row = conn.execute(
        "SELECT COALESCE(SUM(hours_estimated), 0) FROM scope_items WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    scope_hours = scope_row[0] if scope_row else 0

    # Employee summary
    emp_rows = conn.execute("""
        SELECT e.id, e.name, e.position, e.billing_rate,
               COALESCE(SUM(t.hours_allocated), 0) as total_hours
        FROM employees e
        LEFT JOIN tasks t ON t.employee_id = e.id AND t.project_id = ?
        GROUP BY e.id
        ORDER BY total_hours DESC
    """, (project_id,)).fetchall()

    employee_breakdown = []
    for e in emp_rows:
        hours = e["total_hours"] or 0
        cost = hours * (e["billing_rate"] or 0)
        employee_breakdown.append({
            "employee_id": e["id"],
            "name": e["name"],
            "position": e["position"],
            "billing_rate": e["billing_rate"],
            "hours": hours,
            "cost": round(cost, 2),
        })

    conn.close()
    return {
        "total_task_hours": total_task_hours,
        "total_task_cost": round(total_task_cost, 2),
        "scope_hours_estimated": scope_hours,
        "tasks": task_details,
        "employees": employee_breakdown,
    }


# --- Project Summary ---

def get_project_summary(project_id: int) -> dict:
    conn = get_db()
    project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project:
        conn.close()
        return None

    task_counts = conn.execute("""
        SELECT status, COUNT(*) as count FROM tasks
        WHERE project_id = ? GROUP BY status
    """, (project_id,)).fetchall()

    doc_count = conn.execute("SELECT COUNT(*) FROM documents WHERE project_id = ?", (project_id,)).fetchone()[0]
    scope_count = conn.execute("SELECT COUNT(*) FROM scope_items WHERE project_id = ?", (project_id,)).fetchone()[0]

    tasks_by_status = {r["status"]: r["count"] for r in task_counts}

    conn.close()
    return {
        "project": dict(project),
        "task_summary": tasks_by_status,
        "total_documents": doc_count,
        "total_scope_items": scope_count,
        "budget": get_project_budget(project_id),
    }


# Init on import
init_db()
