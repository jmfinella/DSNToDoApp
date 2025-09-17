from typing import List, Dict, Any
from storage.pocketbase import PocketBaseClient
from services.events_service import DailyOps


class AppController:
    """Coordina la UI con el backend (PocketBase) y servicios de dominio."""
    def __init__(self, client: PocketBaseClient):
        self.client = client
        self.main_window=None
        self.menu=None
        
    # ---- UI integration ----
    def set_main_window(self,window):
        self.main_window=window
        
    def set_menu(self,menu):
        self.menu=menu
        self.configure_task_menu(self.menu)
    
    def configure_task_menu(self, menu):
        """Configura un menú contextual para la tarea dada."""
        menu.add_command(label="Editar", command=lambda: self._edit_task(task_id))
        menu.add_command(label="Archivar", command=lambda: self._archive_task(task_id))
   
    def show_task_menu(self, task_id: str, task: Dict[str, Any] = None):
        """Muestra el menú contextual para la tarea dada."""    
        try:
            self.menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            self.menu.grab_release()
            
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
    
    def list_all_tasks(self, context_id: str) -> List[Dict[str, Any]]:
        return self.client.list_tasks(context_id, status="all")
    
    def add_task(self, context_id: str, title: str) -> Dict[str, Any]:
        # posición naive: al final
        items = self.client.list_tasks(context_id, status="open")
        pos = max([(i.get("position") or 1.0) for i in items], default=0.0) + 1.0
        return self.client.create_task(title=title, context_id=context_id, position=pos, kind="todo")

    def toggle_done(self, task: Dict[str, Any]) -> Dict[str, Any]:
        new_status = "open" if task.get("status") == "done" else "done"
        return self.client.patch_task(task["id"], status=new_status)

    # ---- daily ops ----
    def prepare_day(self):
        svc = DailyOps(self.client.base_url, self.client.token, self.client.user_id)
        svc.prepare_today()

    def open_task_menu(self, task_id: str):
        """Abre un menú contextual para la tarea dada."""
        pass

##A IMPLEMENTAR:

    def archive(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return self.client.patch_task(task["id"], status="archived")
    
    # Opcional: helper semántico
    def rename_task(self, task_id: str, new_title: str) -> Dict[str, Any]:
        return self.update_task(task_id, title=new_title)

    # Si manejas due/priority como edición:
    def set_due(self, task_id: str, due_iso: str) -> Dict[str, Any]:
        return self.update_task(task_id, due_date=due_iso)

    def set_priority(self, task_id: str, priority: int) -> Dict[str, Any]:
        return self.update_task(task_id, priority=priority)
    
    def update_task(self, task_id: str, **fields) -> Dict[str, Any]:
        """Editar/patch de una tarea."""
        return self.client.patch_task(task_id, **fields)

    def create_subtask_a(self, parent_task_id: str, title: str) -> Dict[str, Any]:
        """Crea una subtarea colgando de parent_task."""
        # Listar hermanas para calcular position
        try:
            siblings = self.client.list_tasks(
                context_id=None, status="open", parent_task=parent_task_id
            )
        except TypeError:
            # Alternativa si tu cliente usa otro nombre/forma de filtro:
            siblings = self.client.list_subtasks(parent_task_id)  # si existe

        pos = max([(s.get("position") or 1.0) for s in siblings], default=0.0) + 1.0
        return self.client.create_task(
            title=title,
            context_id=None,          # si tus subtareas no heredan contexto; ajusta si corresponde
            parent_task=parent_task_id,   # <-- tu schema
            position=pos,
            kind="subtask",
            status="open",
        )

    def create_subtask_b(self, parent_task_id: str, title: str) -> Dict[str, Any]:
        """Crear una subtarea ligada a una tarea padre."""
        # posición naive al final dentro del grupo del padre
        siblings = self.client.list_subtasks(parent_task_id)  # si no lo tienes, usa un filtro list_tasks(...)
        pos = max([(s.get("position") or 1.0) for s in siblings], default=0.0) + 1.0
        return self.client.create_task(
            title=title,
            context_id=None,            # si tus subtareas no tienen contexto propio
            parent_id=parent_task_id,   # <-- campo que tu schema soporte (p.ej. parent_id)
            position=pos,
            kind="subtask",
            status="open",
        )
