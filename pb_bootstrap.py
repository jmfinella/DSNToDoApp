# ==== pb_bootstrap.py (script AUTÓNOMO, completo) ====
# Crea/actualiza colecciones para Bullet Journal en PocketBase usando Admin API.
# Ejecutar con:  python pb_bootstrap.py

import sys
import requests

PB_BASE = "http://100.117.43.98:8090"   # <-- tu server
ADMIN_EMAIL = "jmfinella@gmail.com"        # <-- admin del panel
ADMIN_PASSWORD = "72dcPYZmG5G7k96"        # <-- contraseña admin

def die(msg):
    print(msg)
    sys.exit(1)

class PBAdmin:
    def __init__(self, base):
        self.base = base.rstrip('/')
        self.s = requests.Session()

    def admin_login(self, email, password):
        r = self.s.post(f"{self.base}/api/admins/auth-with-password", json={
            "identity": email,
            "password": password
        }, timeout=15)
        if not r.ok:
            die(f"[LOGIN] {r.status_code}: {r.text}")
        tok = r.json().get("token")
        if not tok:
            die("[LOGIN] token faltante")
        self.s.headers.update({"Authorization": f"Bearer {tok}"})
        print("[OK] Admin login")

    def get_collection(self, name_or_id):
        r = self.s.get(f"{self.base}/api/collections/{name_or_id}", timeout=15)
        if r.status_code == 404:
            return None
        if not r.ok:
            die(f"[GET {name_or_id}] {r.status_code}: {r.text}")
        return r.json()

    def create_collection(self, payload):
        r = self.s.post(f"{self.base}/api/collections", json=payload, timeout=20)
        if not r.ok:
            die(f"[CREATE {payload.get('name')}] {r.status_code}: {r.text}")
        return r.json()

    def update_collection(self, id_or_name, payload):
        r = self.s.patch(f"{self.base}/api/collections/{id_or_name}", json=payload, timeout=20)
        if not r.ok:
            die(f"[UPDATE {id_or_name}] {r.status_code}: {r.text}")
        return r.json()


def spec_contexts():
    return {
        "name": "contexts",
        "type": "base",
        "schema": [
            {"name": "name", "type": "text", "required": True, "options": {"min": 1, "max": 120}},
            {"name": "color", "type": "text", "required": False, "options": {"pattern": "^#?[0-9A-Fa-f]{3,8}$"}},
            {"name": "owner", "type": "relation", "required": True,
             "options": {"collectionId": "_pb_users_auth_", "cascadeDelete": True, "maxSelect": 1}}
        ],
        "indexes": [
            "CREATE UNIQUE INDEX idx_contexts_owner_name ON contexts (owner, name)"
        ],
        "listRule": "owner = @request.auth.id",
        "viewRule": "owner = @request.auth.id",
        "createRule": "@request.auth.id != ''",
        "updateRule": "owner = @request.auth.id",
        "deleteRule": "owner = @request.auth.id"
    }


def spec_journal_pages():
    return {
        "name": "journal_pages",
        "type": "base",
        "schema": [
            {"name": "date", "type": "date", "required": True, "options": {}},
            {"name": "owner", "type": "relation", "required": True,
             "options": {"collectionId": "_pb_users_auth_", "cascadeDelete": True, "maxSelect": 1}}
        ],
        "indexes": [
            "CREATE UNIQUE INDEX idx_jp_owner_date ON journal_pages (owner, date)"
        ],
        "listRule": "owner = @request.auth.id",
        "viewRule": "owner = @request.auth.id",
        "createRule": "@request.auth.id != ''",
        "updateRule": "owner = @request.auth.id",
        "deleteRule": "owner = @request.auth.id"
    }


def spec_tasks(contexts_id: str, tasks_id: str | None = None):
    schema = [
        {"name": "title", "type": "text", "required": True, "options": {"min": 1, "max": 200}},
        {"name": "notes", "type": "text", "required": False, "options": {"max": 5000}},
        {"name": "status", "type": "select", "required": True,
         "options": {"maxSelect": 1, "values": ["open", "done", "cancelled", "archived"]}},
        {"name": "kind", "type": "select", "required": True,
         "options": {"maxSelect": 1, "values": ["todo", "event", "routine"]}},
        {"name": "priority", "type": "number", "required": False, "options": {"min": -5, "max": 5}},
        {"name": "position", "type": "number", "required": False, "options": {}},
        {"name": "context", "type": "relation", "required": True,
         "options": {"collectionId": contexts_id, "cascadeDelete": False, "maxSelect": 1}},
        {"name": "owner", "type": "relation", "required": True,
         "options": {"collectionId": "_pb_users_auth_", "cascadeDelete": True, "maxSelect": 1}},
        # Bullet: fechas
        {"name": "journal_date", "type": "date", "required": False, "options": {}},
        {"name": "scheduled_for", "type": "date", "required": False, "options": {}},
        {"name": "due_date", "type": "date", "required": False, "options": {}},
        # Eventos (agenda)
        {"name": "start_at", "type": "date", "required": False, "options": {}},
        {"name": "end_at", "type": "date", "required": False, "options": {}},
        # Recurrencias (RRULE)
        {"name": "recurrence", "type": "text", "required": False, "options": {"max": 300}},
        {"name": "migrated_count", "type": "number", "required": False, "options": {"min": 0, "max": 10000}},
    ]
    if tasks_id:
        schema.append({
            "name": "parent_task", "type": "relation", "required": False,
            "options": {"collectionId": tasks_id, "cascadeDelete": False, "maxSelect": 1}
        })
    return {
        "name": "tasks",
        "type": "base",
        "schema": schema,
        "indexes": [
            "CREATE INDEX idx_tasks_owner_ctx_date ON tasks (owner, context, journal_date)",
            "CREATE INDEX idx_tasks_owner_status_due ON tasks (owner, status, due_date)",
            "CREATE INDEX idx_tasks_owner_recurrence ON tasks (owner, recurrence)"
        ],
        "listRule": "owner = @request.auth.id",
        "viewRule": "owner = @request.auth.id",
        "createRule": "@request.auth.id != ''",
        "updateRule": "owner = @request.auth.id",
        "deleteRule": "owner = @request.auth.id"
    }


def upsert_collection(pb: PBAdmin, spec: dict):
    existing = pb.get_collection(spec["name"])
    if not existing:
        return pb.create_collection(spec)
    cid = existing.get("id") or spec["name"]
    # Asegura que el nombre permanezca igual para patch por id
    spec_with_id_name = spec.copy()
    spec_with_id_name["id"] = cid
    spec_with_id_name["name"] = existing["name"]
    return pb.update_collection(cid, spec_with_id_name)


def main():
    pb = PBAdmin(PB_BASE)
    pb.admin_login(ADMIN_EMAIL, ADMIN_PASSWORD)

    # 1) contexts
    ctx = upsert_collection(pb, spec_contexts())
    contexts_id = ctx.get("id")
    print("OK: contexts", contexts_id)

    # 2) journal_pages
    jp = upsert_collection(pb, spec_journal_pages())
    print("OK: journal_pages", jp.get("id"))

    # 3) tasks (fase 1 sin self‑relation)
    t1 = upsert_collection(pb, spec_tasks(contexts_id, tasks_id=None))
    tasks_id = t1.get("id")
    print("OK: tasks (phase1)", tasks_id)

    # 4) tasks (fase 2 agrega parent_task con collectionId correcto)
    t2 = upsert_collection(pb, spec_tasks(contexts_id, tasks_id=tasks_id))
    print("OK: tasks (phase2 parent_task added)", t2.get("id"))

    print("Bootstrap completo.")

if __name__ == "__main__":
    main()