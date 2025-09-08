from typing import List, Dict, Any
from ..storage.pocketbase import PocketBaseClient
from ..services.events_service import DailyOps


class AppController:
    """Coordina la UI con el backend (PocketBase) y servicios de dominio."""
    def __init__(self, client: PocketBaseClient):
        self.client = client

    # ---- contexts ----
    def load_contexts(self) -> List[Dict[str, Any]]:
        ctx = self.client.list_contexts()
        if not ctx:
            self.client.ensure_context("Laboral", "#2E86DE")
            self.client.ensure_context("Personal", "#27AE60")
            ctx = self.client.list_contexts()
        return ctx

    # ---- tasks ----
    def list_open_tasks(self, context_id: str) -> List[Dict[str, Any]]:
        return self.client.list_tasks(context_id, status="open")

    def add_task(self, context_id: str, title: str) -> Dict[str, Any]:
        # posición naive: al final
        items = self.client.list_tasks(context_id, status="open")
        pos = max([(i.get("position") or 1.0) for i in items], default=0.0) + 1.0
        return self.client.create_task(title=title, context_id=context_id, position=pos, kind="todo")

    def toggle_done(self, task: Dict[str, Any]) -> Dict[str, Any]:
        new_status = "open" if task.get("status") == "done" else "done"
        return self.client.patch_task(task["id"], status=new_status)

    def archive(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return self.client.patch_task(task["id"], status="archived")

    # ---- daily ops ----
    def prepare_day(self):
        svc = DailyOps(self.client.base_url, self.client.token, self.client.user_id)
        svc.prepare_today()