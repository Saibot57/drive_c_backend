"""
Command Center – lokalt integrationstestskript.

Kör med:
    cd drive_c_backend
    python tests/test_command_center.py

Kräver att Flask-servern körs lokalt (python app.py) och att
TEST_USERNAME / TEST_PASSWORD finns i miljön (eller hårdkodas nedan).
"""

import os
import sys
import requests

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:5001/api")
USERNAME = os.getenv("TEST_USERNAME", "")
PASSWORD = os.getenv("TEST_PASSWORD", "")

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
    return condition


def get_token() -> str:
    r = requests.post(f"{BASE_URL}/auth/login", json={"username": USERNAME, "password": PASSWORD})
    data = r.json()
    assert data.get("success"), f"Login failed: {data}"
    return data["data"]["token"]


def run_tests():
    if not USERNAME or not PASSWORD:
        print("ERROR: Set TEST_USERNAME and TEST_PASSWORD environment variables.")
        sys.exit(1)

    print("\n=== Command Center – Integration Tests ===\n")
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    errors = 0

    # ------------------------------------------------------------------
    # TEMPLATES
    # ------------------------------------------------------------------
    print("--- Templates ---")

    # Create
    r = requests.post(f"{BASE_URL}/command-center/templates",
                      json={"name": "Mötesanteckning", "skeleton": "## Agenda\n\n## Beslut"},
                      headers=headers)
    ok = r.status_code == 201 and r.json().get("success")
    if not check("POST /templates", ok, str(r.status_code)):
        errors += 1
    template_id = r.json()["data"]["id"] if ok else None

    # List
    r = requests.get(f"{BASE_URL}/command-center/templates", headers=headers)
    ok = r.status_code == 200 and isinstance(r.json()["data"], list)
    if not check("GET /templates", ok):
        errors += 1

    # Update
    if template_id:
        r = requests.put(f"{BASE_URL}/command-center/templates/{template_id}",
                         json={"name": "Uppdaterad mall"},
                         headers=headers)
        ok = r.status_code == 200 and r.json()["data"]["name"] == "Uppdaterad mall"
        if not check("PUT /templates/<id>", ok):
            errors += 1

    # Delete
    if template_id:
        r = requests.delete(f"{BASE_URL}/command-center/templates/{template_id}", headers=headers)
        ok = r.status_code == 200 and r.json()["data"]["deleted_id"] == template_id
        if not check("DELETE /templates/<id>", ok):
            errors += 1

    # ------------------------------------------------------------------
    # NOTES
    # ------------------------------------------------------------------
    print("\n--- Notes ---")

    # Create
    r = requests.post(f"{BASE_URL}/command-center/notes",
                      json={"title": "Testanteckning", "content": "Hej världen", "tags": ["test", "dev"]},
                      headers=headers)
    ok = r.status_code == 201 and r.json().get("success")
    if not check("POST /notes", ok, str(r.status_code)):
        errors += 1
    note_id = r.json()["data"]["id"] if ok else None
    if ok:
        check("  tags deserialiseras som lista", isinstance(r.json()["data"]["tags"], list))

    # List
    r = requests.get(f"{BASE_URL}/command-center/notes", headers=headers)
    ok = r.status_code == 200 and isinstance(r.json()["data"], list)
    if not check("GET /notes", ok):
        errors += 1

    # Get single
    if note_id:
        r = requests.get(f"{BASE_URL}/command-center/notes/{note_id}", headers=headers)
        ok = r.status_code == 200 and r.json()["data"]["id"] == note_id
        if not check("GET /notes/<id>", ok):
            errors += 1

    # Update
    if note_id:
        r = requests.put(f"{BASE_URL}/command-center/notes/{note_id}",
                         json={"title": "Uppdaterad", "tags": ["uppdaterad"]},
                         headers=headers)
        ok = r.status_code == 200 and r.json()["data"]["title"] == "Uppdaterad"
        if not check("PUT /notes/<id>", ok):
            errors += 1

    # Delete
    if note_id:
        r = requests.delete(f"{BASE_URL}/command-center/notes/{note_id}", headers=headers)
        ok = r.status_code == 200 and r.json()["data"]["deleted_id"] == note_id
        if not check("DELETE /notes/<id>", ok):
            errors += 1

    # 404 på borttagen note
    if note_id:
        r = requests.get(f"{BASE_URL}/command-center/notes/{note_id}", headers=headers)
        if not check("GET /notes/<id> efter delete → 404", r.status_code == 404):
            errors += 1

    # ------------------------------------------------------------------
    # TODOS
    # ------------------------------------------------------------------
    print("\n--- Todos ---")

    # Create date-todo
    r = requests.post(f"{BASE_URL}/command-center/todos",
                      json={"content": "Köp mjölk", "type": "date", "target_date": "2025-03-15"},
                      headers=headers)
    ok = r.status_code == 201 and r.json().get("success")
    if not check("POST /todos (type=date)", ok, str(r.status_code)):
        errors += 1
    todo_id = r.json()["data"]["id"] if ok else None

    # Create week-todo
    r = requests.post(f"{BASE_URL}/command-center/todos",
                      json={"content": "Veckoplanering", "type": "week", "week_number": 12},
                      headers=headers)
    ok = r.status_code == 201 and r.json().get("success")
    if not check("POST /todos (type=week)", ok):
        errors += 1
    week_todo_id = r.json()["data"]["id"] if ok else None

    # List all
    r = requests.get(f"{BASE_URL}/command-center/todos", headers=headers)
    ok = r.status_code == 200 and isinstance(r.json()["data"], list)
    if not check("GET /todos", ok):
        errors += 1

    # List filtered by week
    r = requests.get(f"{BASE_URL}/command-center/todos?type=week&week=12", headers=headers)
    ok = r.status_code == 200 and all(t["type"] == "week" for t in r.json()["data"])
    if not check("GET /todos?type=week&week=12", ok):
        errors += 1

    # Update status
    if todo_id:
        r = requests.put(f"{BASE_URL}/command-center/todos/{todo_id}",
                         json={"status": "done"},
                         headers=headers)
        ok = r.status_code == 200 and r.json()["data"]["status"] == "done"
        if not check("PUT /todos/<id> (status=done)", ok):
            errors += 1

    # Validation: invalid type
    r = requests.post(f"{BASE_URL}/command-center/todos",
                      json={"content": "Test", "type": "invalid"},
                      headers=headers)
    if not check("POST /todos med ogiltigt type → 400", r.status_code == 400):
        errors += 1

    # Delete
    for tid in [todo_id, week_todo_id]:
        if tid:
            r = requests.delete(f"{BASE_URL}/command-center/todos/{tid}", headers=headers)
            ok = r.status_code == 200
            if not check(f"DELETE /todos/{tid}", ok):
                errors += 1

    # ------------------------------------------------------------------
    # Sammanfattning
    # ------------------------------------------------------------------
    print(f"\n{'='*40}")
    if errors == 0:
        print(f"  {PASS} Alla tester gick igenom!")
    else:
        print(f"  {FAIL} {errors} test(er) misslyckades.")
    print('='*40)
    sys.exit(0 if errors == 0 else 1)


if __name__ == "__main__":
    run_tests()
