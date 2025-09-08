import datetime as dt
from typing import Dict
import requests


class DailyOps:
    """Operaciones del día: crear página diaria, mover pendientes, materializar rutinas, ajustar eventos."""
    def __init__(self, base_url: str, user_token: str, user_id: str):
        self.base = base_url.rstrip('/')
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {user_token}"})
        self.user_id = user_id

    def _ensure_page(self, date_iso: str) -> Dict:
        start = f"{date_iso} 00:00:00Z"
        next_day = (dt.date.fromisoformat(date_iso) + dt.timedelta(days=1)).isoformat()
        end = f"{next_day} 00:00:00Z"
        filt = f'owner = "{self.user_id}" && date >= "{start}" && date < "{end}"'
        r = self.s.get(f"{self.base}/api/collections/journal_pages/records", params={"filter": filt, "perPage": 1}, timeout=10)
        r.raise_for_status()
        items = r.json().get("items", [])
        if items:
            return items[0]
        # create normalized at 00:00Z; handle race by retrying fetch
        try:
            r = self.s.post(f"{self.base}/api/collections/journal_pages/records", json={"date": start, "owner": self.user_id}, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception:
            r = self.s.get(f"{self.base}/api/collections/journal_pages/records", params={"filter": filt, "perPage": 1}, timeout=10)
            r.raise_for_status()
            items = r.json().get("items", [])
            if items:
                return items[0]
            raise

    def prepare_today(self, today: dt.date | None = None):
        if today is None:
            today = dt.date.today()
        yesterday = today - dt.timedelta(days=1)
        today_iso = today.isoformat()
        y_iso = yesterday.isoformat()

        self._ensure_page(today_iso)

        # mover tareas 'open' de ayer a hoy (solo kind=todo)
        rf = f'owner = "{self.user_id}" && status = "open" && journal_date = "{y_iso}" && kind = "todo"'
        r = self.s.get(f"{self.base}/api/collections/tasks/records", params={"filter": rf, "perPage": 500}, timeout=15)
        r.raise_for_status()
        for t in r.json().get("items", []):
            migrated = (t.get("migrated_count") or 0) + 1
            self.s.patch(f"{self.base}/api/collections/tasks/records/{t['id']}", json={"journal_date": today_iso, "migrated_count": migrated}, timeout=10).raise_for_status()

        # materializar rutinas semanales (FREQ=WEEKLY;BYDAY=...)
        weekday_map = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
        today_token = weekday_map[today.weekday()]
        r = self.s.get(f"{self.base}/api/collections/tasks/records", params={"filter": f'owner = "{self.user_id}" && kind = "routine" && recurrence != ""', "perPage": 500}, timeout=15)
        r.raise_for_status()
        for rt in r.json().get("items", []):
            rrule = (rt.get("recurrence") or "").upper()
            if "FREQ=WEEKLY" not in rrule:
                continue
            byday = []
            for part in rrule.split(";"):
                if part.startswith("BYDAY="):
                    byday = [p.strip() for p in part.replace("BYDAY=", "").split(",") if p.strip()]
            if byday and today_token not in byday:
                continue
            # evitar duplicado
            chk = self.s.get(f"{self.base}/api/collections/tasks/records", params={"filter": f'owner = "{self.user_id}" && parent_task = "{rt["id"]}" && journal_date = "{today_iso}"', "perPage": 1}, timeout=10)
            chk.raise_for_status()
            if chk.json().get("items"):
                continue
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

        # eventos del día → asegurar que aparezcan en la página de hoy
        evf = (f'owner = "{self.user_id}" && kind = "event" '
               f'&& start_at >= "{today_iso} 00:00:00Z" && start_at < "{today_iso} 23:59:59Z"')
        r = self.s.get(f"{self.base}/api/collections/tasks/records", params={"filter": evf, "perPage": 500}, timeout=15)
        r.raise_for_status()
        for ev in r.json().get("items", []):
            if ev.get("journal_date") != today_iso:
                self.s.patch(f"{self.base}/api/collections/tasks/records/{ev['id']}", json={"journal_date": today_iso}, timeout=10).raise_for_status()