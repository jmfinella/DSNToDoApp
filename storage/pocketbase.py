from __future__ import annotations
import requests
from typing import List, Dict, Any, Optional
from core.exceptions import PBError


class PocketBaseClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.token: Optional[str] = ""
        self.user_id: Optional[str] = ""

    # ---------- auth ----------
    def login(self, identity: str, password: str) -> bool:
        url = f"{self.base_url}/api/collections/users/auth-with-password"
        r = self.session.post(url, json={"identity": identity, "password": password}, timeout=10)
        if not r.ok:
            raise PBError(f"Login failed: {r.status_code} {r.text}")
        data = r.json()
        self.token = data.get("token")
        self.user_id = data.get("record", {}).get("id")
        if not self.token or not self.user_id:
            raise PBError("Missing token or user id in login response")
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        return True

    # ---------- contexts ----------
    def list_contexts(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/api/collections/contexts/records"
        r = self.session.get(url, params={"filter": f'owner = "{self.user_id}"', "perPage": 200}, timeout=10)
        if not r.ok:
            raise PBError(r.text)
        return r.json().get("items", [])

    def ensure_context(self, name: str, color: Optional[str] = None) -> Dict[str, Any]:
        # get by name for owner
        url = f"{self.base_url}/api/collections/contexts/records"
        r = self.session.get(url, params={"filter": f'name = "{name}" && owner = "{self.user_id}"', "perPage": 1}, timeout=10)
        if r.ok and r.json().get("items"):
            return r.json()["items"][0]
        # create
        payload = {"name": name, "owner": self.user_id}
        if color:
            payload["color"] = color
        r = self.session.post(f"{self.base_url}/api/collections/contexts/records", json=payload, timeout=10)
        if not r.ok:
            raise PBError(r.text)
        return r.json()

    # ---------- tasks ----------
    def list_tasks(self, context_id: str, status: str = "all") -> List[Dict[str, Any]]:
        url = f"{self.base_url}/api/collections/tasks/records"
        filt = f'owner = "{self.user_id}" && context = "{context_id}"' if context_id and context_id != 'all' else f'owner = "{self.user_id}"'
        if status:
            if status == "all":
                filt += f' && status = "open" || status = "done" || status = "cancelled"'
            else:
                filt += f' && status = "{status}"'
        r = self.session.get(url, params={"filter": filt, "sort": "position,-priority,created", "perPage": 500}, timeout=10)
        if not r.ok:
            raise PBError(r.text)
        return r.json().get("items", [])

    def create_task(self, *, title: str, context_id: str, position: float = 1.0, priority: int = 0,
                    kind: str = "todo", journal_date: Optional[str] = None) -> Dict[str, Any]:
        import datetime as dt
        if journal_date is None:
            journal_date = dt.date.today().isoformat()
        payload = {
            "title": title,
            "status": "open",
            "kind": kind,
            "priority": priority,
            "position": position,
            "context": context_id,
            "owner": self.user_id,
            "journal_date": journal_date,
        }
        r = self.session.post(f"{self.base_url}/api/collections/tasks/records", json=payload, timeout=10)
        if not r.ok:
            raise PBError(f"Create task failed: {r.status_code} {r.text}")
        return r.json()

    def patch_task(self, task_id: str, **fields) -> Dict[str, Any]:
        url = f"{self.base_url}/api/collections/tasks/records/{task_id}"
        r = self.session.patch(url, json=fields, timeout=10)
        if not r.ok:
            raise PBError(r.text)
        return r.json()