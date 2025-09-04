"""
Minimal To‑Do app (Tkinter) backed by PocketBase.

Features
- Login with email/password (PocketBase users collection)
- Tabs = contexts (Laboral, Personal, ...)
- List open tasks per context
- Add new task (quick entry)
- Toggle done (Space / double‑click)
- Archive task (Del)
- Pull sync every 30s (configurable)

PocketBase prerequisites
- Collections: users (built‑in), contexts, tasks
- tasks fields: title (text), status (select: open/done/archived, default open),
    priority (number default 0), position (number), notes (text optional),
    due_date (date optional), context (relation->contexts, required), owner (relation->users, required)
- contexts fields: name (text), color (text optional), owner (relation->users required)
- Rules suggested (per‑user): owner = @request.auth.id

Edit BASE_URL, EMAIL, PASSWORD below.

Tested with Python 3.10+
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox as mb
import time
import uuid
import requests
import datetime as dt
import threading
import json as _json
try:
    from websocket import WebSocketApp
except Exception:
    WebSocketApp = None  # si falta la lib, la app sigue con pull cada X seg

# ===================== CONFIG =====================
BASE_URL = "http://100.117.43.98:8090/"  # PocketBase serve address
EMAIL = "jmfinella@gmail.com"      
PASSWORD = "adminadmin"
USER = "jmfinella"             
SYNC_INTERVAL_MS = 60_000  # 60s; el realtime hará la mayor parte

# ============== PocketBase client (simple) ===============
class PBError(Exception):
    pass

class PocketBaseClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.token: str | None = None
        self.user_id: str | None = None
        self.session = requests.Session()

    # ---------- auth ----------
    def login(self, email: str, password: str):
        url = f"{self.base_url}/api/collections/users/auth-with-password"
        r = self.session.post(url, json={"identity": email, "password": password}, timeout=10)
        if not r.ok:
            raise PBError(f"Login failed: {r.status_code} {r.text}")
        data = r.json()
        self.token = data.get("token")
        self.user_id = data.get("record", {}).get("id")
        if not self.token or not self.user_id:
            raise PBError("Missing token or user id in login response")
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})

    # ---------- contexts ----------
    def list_contexts(self) -> list[dict]:
        url = f"{self.base_url}/api/collections/contexts/records"
        r = self.session.get(url, params={"filter": f'owner = "{self.user_id}"', "perPage": 200}, timeout=10)
        if not r.ok:
            raise PBError(r.text)
        return r.json().get("items", [])

    def ensure_context(self, name: str, color: str | None = None) -> dict:
        # get by name
        url = f"{self.base_url}/api/collections/contexts/records"
        r = self.session.get(url, params={"filter": f'name = "{name}" && owner = "{self.user_id}"', "perPage": 1}, timeout=10)
        if r.ok and r.json().get("items"):
            return r.json()["items"][0]
        # create
        url = f"{self.base_url}/api/collections/contexts/records"
        payload = {"name": name, "owner": self.user_id}
        if color:
            payload["color"] = color
        r = self.session.post(url, json=payload, timeout=10)
        if not r.ok:
            raise PBError(r.text)
        return r.json()

    # ---------- tasks ----------
    def list_tasks(self, context_id: str, status: str = "open") -> list[dict]:
        url = f"{self.base_url}/api/collections/tasks/records"
        filt = f'owner = "{self.user_id}" && context = "{context_id}"'
        if status:
            filt += f' && status = "{status}"'
        r = self.session.get(url, params={"filter": filt, "sort": "position,-priority,created", "perPage": 500}, timeout=10)
        if not r.ok:
            raise PBError(r.text)
        return r.json().get("items", [])

    def create_task(self, title: str, context_id: str, position: float = 1.0, priority: int = 0,
        kind: str = "todo", journal_date: str | None = None) -> dict:
        url = f"{self.base_url}/api/collections/tasks/records"
        if journal_date is None:
            journal_date = dt.date.today().isoformat()
        payload = {
        "title": title,
        "status": "open",
        "kind": kind, # requerido por el esquema
        "priority": priority,
        "position": position,
        "context": context_id,
        "owner": self.user_id,
        "journal_date": journal_date
        }
        r = self.session.post(url, json=payload, timeout=10)
        if not r.ok:
            raise PBError(f"Create task failed: {r.status_code} {r.text}")
        return r.json()

    def patch_task(self, task_id: str, **fields) -> dict:
        url = f"{self.base_url}/api/collections/tasks/records/{task_id}"
        r = self.session.patch(url, json=fields, timeout=10)
        if not r.ok:
            raise PBError(r.text)
        return r.json()

# ================== Tkinter UI ==================
class ToDoApp(tk.Tk):
    def __init__(self, client: PocketBaseClient):
        super().__init__()
        self.client = client
        self.title("To‑Do PB · Minimal")
        self.geometry("520x480")
        self.configure(padx=8, pady=8)
        self.attributes("-topmost", True)

        # Top bar: context actions
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0,6))
        ttk.Button(top, text="Sync", command=self.sync_all).pack(side="right")
        self.status_var = tk.StringVar(value="Listo")
        ttk.Label(top, textvariable=self.status_var).pack(side="left")
        ttk.Button(top, text="Preparar día", command=self.prepare_day).pack(side="right", padx=(6,0))

        # Notebook (tabs per context)
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self._rt_lock = threading.Lock()
        self._rt_pending = False
        #self._load_contexts_build_tabs()
        self._start_realtime()   # <- inicia realtime
        self.context_tabs: dict[str, ContextTab] = {}

        self.bind("<F5>", lambda e: self.sync_all())
        self.after(SYNC_INTERVAL_MS, self._auto_sync)

        # Load contexts and build tabs
        self._load_contexts_build_tabs()

    def prepare_day(self):
        """Ejecuta el rollover + materialización de rutinas para HOY (usuario actual)."""
        try:
            DailyOps(BASE_URL, self.client.token, self.client.user_id).prepare_today()
            self.sync_all()
            self.status_var.set("Día preparado ✓")
        except Exception as e:
            mb.showerror("Preparar día", f"Falló preparar el día:\n{e}")
            print("prepare_day error:", e)
        
    def _start_realtime(self):
        # Fallback: desactivar WS si no hay lib o si el BASE_URL está detrás de proxy que no hace upgrade
        if WebSocketApp is None:
            print("[realtime] websocket-client no instalado; uso pull cada", SYNC_INTERVAL_MS, "ms")
            return

        base = BASE_URL.rstrip('/')
        ws_url = base.replace('https://', 'wss://').replace('http://', 'ws://') + "/api/realtime"
        headers = [f"Authorization: Bearer {self.client.token}"]

        def on_open(ws):
            sub = {"id": "sub_tasks", "type": "subscribe", "collection": "tasks",
                "filter": f'owner = "{self.client.user_id}"'}
            ws.send(_json.dumps(sub))
            print("[realtime] suscripto OK")

        def on_message(ws, message):
            if not self.winfo_exists():
                return
            with self._rt_lock:
                if not self._rt_pending:
                    self._rt_pending = True
                    try:
                        self.after(300, self._rt_apply)
                    except tk.TclError:
                        pass

        def on_error(ws, error):
            print("[realtime] deshabilitado (", error, "); continúo con pull cada", SYNC_INTERVAL_MS, "ms")

        try:
            self._ws = WebSocketApp(ws_url, header=headers,
                                    on_open=on_open, on_message=on_message, on_error=on_error)
            threading.Thread(target=self._ws.run_forever, daemon=True).start()
        except Exception as e:
            print("[realtime] error al iniciar:", e, "; uso pull.")

    def _rt_apply(self):
        if not self.winfo_exists():
            return
        with self._rt_lock:
            self._rt_pending = False
        self.sync_all()
    # ---------- contexts init ----------
    def _load_contexts_build_tabs(self):
        try:
            contexts = self.client.list_contexts()
            # Bootstrap: create default ones if empty
            if not contexts:
                self.client.ensure_context("Laboral", "#2E86DE")
                self.client.ensure_context("Personal", "#27AE60")
                contexts = self.client.list_contexts()
            # Build tabs
            for c in contexts:
                if c["id"] not in self.context_tabs:
                    tab = ContextTab(self.nb, self.client, c)
                    self.nb.add(tab, text=c.get("name", "Context"))
                    self.context_tabs[c["id"]] = tab
            self.sync_all()
        except Exception as e:
            mb.showerror("Error", f"No se pudieron cargar contextos:\n{e}")
            print(f"No se pudieron cargar contextos:\n{e}")

    # ---------- sync ----------
    def sync_all(self):
        changed = 0
        for tab in self.context_tabs.values():
            changed += tab.refresh_tasks()
        self.status_var.set(f"Sincronizado {time.strftime('%H:%M:%S')} · {changed} items")

    def _auto_sync(self):
        try:
            self.sync_all()
        finally:
            self.after(SYNC_INTERVAL_MS, self._auto_sync)

class DailyOps:
    def __init__(self, base_url: str, user_token, user_id):
        self.base = base_url.rstrip('/')
        import requests as _rq
        self.s = _rq.Session()
        self.s.headers.update({"Authorization": f"Bearer {user_token}"})
        self.user_id = user_id

    def _ensure_page(self, date_iso: str) -> dict:
        r = self.s.get(f"{self.base}/api/collections/journal_pages/records",
                    params={"filter": f'owner = "{self.user_id}" && date = "{date_iso}"', "perPage": 1}, timeout=10)
        r.raise_for_status()
        items = r.json().get("items", [])
        if items:
            return items[0]
        r = self.s.post(f"{self.base}/api/collections/journal_pages/records",
                        json={"date": date_iso, "owner": self.user_id}, timeout=10)
        r.raise_for_status()
        return r.json()

    def prepare_today(self, today: dt.date | None = None):
        if today is None:
            today = dt.date.today()
        yesterday = today - dt.timedelta(days=1)
        today_iso = today.isoformat()
        y_iso = yesterday.isoformat()

        # 1) asegurar página de hoy
        self._ensure_page(today_iso)

        # 2) mover tareas 'open' de ayer a hoy (solo kind=todo)
        r = self.s.get(f"{self.base}/api/collections/tasks/records",
                    params={"filter": f'owner = "{self.user_id}" && status = "open" && journal_date = "{y_iso}" && kind = "todo"',
                            "perPage": 500}, timeout=15)
        r.raise_for_status()
        for t in r.json().get("items", []):
            migrated = (t.get("migrated_count") or 0) + 1
            self.s.patch(f"{self.base}/api/collections/tasks/records/{t['id']}",
                        json={"journal_date": today_iso, "migrated_count": migrated}, timeout=10).raise_for_status()

        # 3) materializar rutinas semanales (FREQ=WEEKLY;BYDAY=...)
        weekday_map = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
        today_token = weekday_map[today.weekday()]
        r = self.s.get(f"{self.base}/api/collections/tasks/records",
                    params={"filter": f'owner = "{self.user_id}" && kind = "routine" && recurrence != ""',
                            "perPage": 500}, timeout=15)
        r.raise_for_status()
        routines = r.json().get("items", [])
        for rt in routines:
            rrule = (rt.get("recurrence") or "").upper()
            if "FREQ=WEEKLY" not in rrule:
                continue
            byday = []
            for part in rrule.split(";"):
                if part.startswith("BYDAY="):
                    byday = [p.strip() for p in part.replace("BYDAY=", "").split(",") if p.strip()]
            if byday and today_token not in byday:
                continue
            # evitar duplicados de hoy
            chk = self.s.get(f"{self.base}/api/collections/tasks/records",
                            params={"filter": f'owner = "{self.user_id}" && parent_task = "{rt["id"]}" && journal_date = "{today_iso}"',
                                    "perPage": 1}, timeout=10)
            chk.raise_for_status()
            if chk.json().get("items"):
                continue
            # crear instancia hija
            payload = {
                "title": rt.get("title"),
                "notes": rt.get("notes"),
                "status": "open",
                "kind": "todo",
                "priority": rt.get("priority"),
                "position": 1.0,
                "context": rt.get("context"),
                "owner": self.user_id,
                "journal_date": today_iso,
                "parent_task": rt.get("id")
            }
            self.s.post(f"{self.base}/api/collections/tasks/records", json=payload, timeout=10).raise_for_status()

        # 4) eventos del día: asegurar que se vean en la página de hoy
        evf = (f'owner = "{self.user_id}" && kind = "event" '
            f'&& start_at >= "{today_iso} 00:00:00Z" && start_at < "{today_iso} 23:59:59Z"')
        r = self.s.get(f"{self.base}/api/collections/tasks/records", params={"filter": evf, "perPage": 500}, timeout=15)
        r.raise_for_status()
        for ev in r.json().get("items", []):
            if ev.get("journal_date") != today_iso:
                self.s.patch(f"{self.base}/api/collections/tasks/records/{ev["id"]}",
                            json={"journal_date": today_iso}, timeout=10).raise_for_status()
class ContextTab(ttk.Frame):
    def __init__(self, parent, client: PocketBaseClient, context: dict):
        super().__init__(parent)
        self.client = client
        self.context = context
        self.context_id = context["id"]

        # Header: quick add
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(6,4))
        ttk.Label(header, text="Nueva tarea:").pack(side="left")
        self.entry = ttk.Entry(header)
        self.entry.pack(side="left", fill="x", expand=True, padx=6)
        self.entry.bind("<Return>", self._on_add)
        ttk.Button(header, text="Agregar", command=self._on_add).pack(side="left")

        # Treeview (tasks open)
        cols = ("title", "due", "priority")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=14)
        self.tree.heading("title", text="Tarea")
        self.tree.heading("due", text="Vence")
        self.tree.heading("priority", text="Pri")
        self.tree.column("title", anchor="w", width=400)
        self.tree.column("due", anchor="center", width=90)
        self.tree.column("priority", anchor="center", width=60)
        self.tree.tag_configure("overdue", foreground="#B00020")  # rojo para atrasadas

        self.tree.pack(fill="both", expand=True)

        # bindings
        self.tree.bind("<Double-1>", self._toggle_done_event)
        self.tree.bind("<space>", self._toggle_done_event)
        self.tree.bind("<Delete>", self._archive_event)

        # local cache {item_id: task_dict}
        self.cache: dict[str, dict] = {}

    # ---------- actions ----------
    def _on_add(self, event=None):
        title = self.entry.get().strip()
        if not title:
            return
        try:
            # naive position: biggest + 1
            pos = 1.0
            if self.cache:
                pos = max((t.get("position") or 1.0) for t in self.cache.values()) + 1.0
            t = self.client.create_task(title=title, context_id=self.context_id, position=pos)
            self.entry.delete(0, tk.END)
            self._upsert_task(t)
        except Exception as e:
            mb.showerror("Error", f"No se pudo crear la tarea:\n{e}")

    def _toggle_done_event(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        task = self.cache.get(iid)
        if not task:
            return
        new_status = "done" if task.get("status") != "done" else "open"
        try:
            t = self.client.patch_task(task["id"], status=new_status)
            # If done, remove from open list; if reopened, keep (since we show open-only)
            if t.get("status") == "open":
                self._upsert_task(t)
            else:
                self._remove_task(iid)
        except Exception as e:
            mb.showerror("Error", f"No se pudo actualizar la tarea:\n{e}")

    def _archive_event(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        task = self.cache.get(iid)
        if not task:
            return
        if not mb.askyesno("Archivar", f"¿Archivar la tarea?\n\n{task.get('title')}"):
            return
        try:
            t = self.client.patch_task(task["id"], status="archived")
            self._remove_task(iid)
        except Exception as e:
            mb.showerror("Error", f"No se pudo archivar la tarea:\n{e}")

    # ---------- data/render ----------
    def tasks(self) -> int:
        """Pull open tasks and update tree. Returns number of items shown."""
        try:
            items = self.client.list_tasks(self.context_id, status="open")
        except Exception as e:
            # bubble up minimal; don't spam dialogs here (handled in parent)
            print("Sync error:", e)
            return len(self.cache)
        # build by id for fast compare
        by_id = {t["id"]: t for t in items}

        # remove missing
        to_remove = [iid for iid, t in self.cache.items() if t["id"] not in by_id]
        for iid in to_remove:
            self._remove_task(iid)

        # upsert existing/new preserving row order according to items sequence
        for t in items:
            self._upsert_task(t)

        # reorder tree to match returned order
        order = []
        for t in items:
            iid = self._iid_for(t)
            order.append(iid)
        self.tree.delete(*self.tree.get_children(""))
        for iid in order:
            t = self.cache[iid]
            self.tree.insert("", "end", iid=iid, values=(t.get("title"), t.get("priority", 0)))
        return len(items)

    def _iid_for(self, task: dict) -> str:
        return task.get("id") or str(uuid.uuid4())

    def _upsert_task(self, task: dict):
        iid = self._iid_for(task)
        self.cache[iid] = task

    def _remove_task(self, iid: str):
        self.cache.pop(iid, None)
        try:
            self.tree.delete(iid)
        except tk.TclError:
            pass
    def refresh_tasks(self) -> int:
        """Pull open tasks and update tree. Returns number of items shown."""
        try:
            items = self.client.list_tasks(self.context_id, status="open")
        except Exception as e:
            print("Sync error:", e)
            return len(self.cache)

        by_id = {t["id"]: t for t in items}

        # remove missing
        to_remove = [iid for iid, t in self.cache.items() if t["id"] not in by_id]
        for iid in to_remove:
            self._remove_task(iid)

        # upsert
        for t in items:
            self._upsert_task(t)

        # rebuild view
        self.tree.delete(*self.tree.get_children(""))
        for t in items:
            iid = self._iid_for(t)
            self.tree.insert("", "end", iid=iid,
                            values=(t.get("title"), t.get("priority", 0)))
        return len(items)
# ================== main ==================
def main():
    client = PocketBaseClient(BASE_URL)
    try:
        if not client.login(EMAIL, PASSWORD):
            client.login(USER, PASSWORD)  # try username
    except Exception as e:
        mb.showerror("Login", f"No se pudo iniciar sesión:\n{e}")
        print("Login error:", e)
        return

    # (Opcional) chequeo amistoso de esquema:
    # if not schema_ready(BASE_URL):
    #     mb.showerror("Esquema faltante",
    #                  "No existe la colección 'tasks'.\nCorré primero pb_bootstrap.py (como admin) en el servidor PocketBase.")
    #     return

    app = ToDoApp(client)
    app.mainloop()

if __name__ == "__main__":
    main()





