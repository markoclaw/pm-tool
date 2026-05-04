"""CI smoke tests — run by GitHub Actions."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import db
import parser

def test_project_crud():
    p = db.create_project('CI Test', 'Auto test')
    assert p['id'] > 0
    assert db.get_project(p['id']) is not None
    assert len(db.list_projects()) >= 1
    db.update_project(p['id'], name='CI Test Updated')
    assert db.get_project(p['id'])['name'] == 'CI Test Updated'
    return p['id']

def test_employee_crud():
    e = db.create_employee('Test Engineer', 'Engineer', 150.0)
    assert e['billing_rate'] == 150.0
    db.update_employee(e['id'], position='Senior', billing_rate=175.0)
    updated = db.get_employee(e['id'])
    assert updated['billing_rate'] == 175.0
    return e['id']

def test_task_with_hours(project_id, employee_id):
    t = db.create_task(project_id, 'Test task', 'desc', employee_id=employee_id, hours_allocated=10)
    assert t['hours_allocated'] == 10
    st = db.create_task(project_id, 'Subtask', 'sub', parent_task_id=t['id'], hours_allocated=5, employee_id=employee_id)
    assert st['parent_task_id'] == t['id']
    return t['id']

def test_scope(project_id):
    s = db.add_scope_item(project_id, 'Scope item', 'design', hours_estimated=20)
    assert s['hours_estimated'] == 20

def test_budget(project_id):
    budget = db.get_project_budget(project_id)
    assert budget['total_task_hours'] == 15.0
    assert budget['total_task_cost'] == 2625.0  # 15h * 175/h

def test_parser():
    import openpyxl, tempfile
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Scope'
    ws.append(['Item', 'Category', 'Description', 'Qty', 'Rate', 'Total'])
    ws.append(['Demo', 'demolition', 'Remove concrete', '500', '45', '22500'])
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        wb.save(f.name)
        path = f.name
    try:
        text, ftype = parser.parse_file(path)
        assert 'Demo' in text
        assert 'Remove concrete' in text
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

if __name__ == '__main__':
    pid = test_project_crud()
    eid = test_employee_crud()
    test_task_with_hours(pid, eid)
    test_scope(pid)
    test_budget(pid)
    test_parser()
    
    # Verify server module loads (don't start the server)
    import importlib.util
    spec = importlib.util.spec_from_file_location('server', 'server.py')
    assert spec is not None, 'server.py not found'
    
    db.delete_project(pid)
    print('All CI tests passed')
