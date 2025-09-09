import tkinter as tk
from tkinter import ttk, messagebox as mb
import datetime as dt
from core.config import SYNC_INTERVAL_MS, TOPMOST, WINDOW_GEOMETRY
from controller.app_controller import AppController
from gui.task_list import ScrollableTaskList

class MainWindow(tk.Tk):
    def __init__(self, controller: AppController):
        super().__init__()
        self.controller = controller
        self.title("To-Do PB · MVC")
        self.geometry(WINDOW_GEOMETRY)
        self.configure(padx=8, pady=8)
        if TOPMOST:
            self.attributes("-topmost", True)

        # Top bar
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 6))
        ttk.Button(top, text="Preparar día", command=self._on_prepare_day).pack(side="right", padx=(6, 0))
        ttk.Button(top, text="Sync", command=self._sync_all).pack(side="right")
        self.status_var = tk.StringVar(value="Listo")
        ttk.Label(top, textvariable=self.status_var).pack(side="left")

        # Notebook
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        self.tabs = {}  # context_id -> ContextTab
        self._build_tabs()

        # timers / binds
        self.bind("<F5>", lambda e: self._sync_all())
        self.after(SYNC_INTERVAL_MS, self._auto_sync)

    # ---------- tabs ----------
    def _build_tabs(self):
        try:
            contexts = self.controller.load_contexts()
        except Exception as e:
            mb.showerror("Contextos", f"No se pudieron cargar contextos: {e}")
            return
        for c in contexts:
            ctx_id = c["id"]
            tab = ContextTab(self.nb, self.controller, ctx_id, c.get("name", "Context"))
            self.nb.add(tab, text=c.get("name", "Context"))
            self.tabs[ctx_id] = tab
        self._sync_all()

    # ---------- sync ----------
    def _sync_all(self):
        total = 0
        for tab in self.tabs.values():
            total += tab.refresh()
        self.status_var.set(f"Sincronizado {dt.datetime.now().strftime('%H:%M:%S')} · {total} items")

    def _auto_sync(self):
        try:
            self._sync_all()
        finally:
            self.after(SYNC_INTERVAL_MS, self._auto_sync)

    # ---------- actions ----------
    def _on_prepare_day(self):
        try:
            self.controller.prepare_day()
            self._sync_all()
            self.status_var.set("Día preparado ✓")
        except Exception as e:
            mb.showerror("Preparar día", f"Falló preparar el día: {e}")


class ContextTab(ttk.Frame):
    def __init__(self, parent, controller: AppController, context_id: str, title: str):
        super().__init__(parent)
        self.controller = controller
        self.context_id = context_id
        self._last_task_id = None
        self._tasks_by_id = {}  # cache: id -> task dict

        # Header: quick add
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(6, 4))
        ttk.Label(header, text="Nueva tarea:").pack(side="left")
        self.entry = ttk.Entry(header)
        self.entry.pack(side="left", fill="x", expand=True, padx=6)
        self.entry.bind("<Return>", self._on_add)
        ttk.Button(header, text="Agregar", command=self._on_add).pack(side="left")

        # Scrollable task list (reemplaza Treeview)
        self.task_list = ScrollableTaskList(
            self,
            on_toggle=self._on_toggle_cb,          # recibe (task_id, done)
            on_menu=self._on_menu_cb,              # recibe (task_id)
            on_add_subtask=self._on_add_subtask_cb # recibe (task_id)
        )
        self.task_list.pack(fill="both", expand=True)

        # Atajos equivalentes
        self.bind_all("<space>", self._kb_toggle_last)
        self.bind_all("<Delete>", self._kb_archive_last)

    # ---------- data ----------
    def refresh(self) -> int:
        try:
            items = self.controller.list_all_tasks(self.context_id)
        except Exception as e:
            print("Sync error:", e)
            return 0

        # cache por id para callbacks del controller
        self._tasks_by_id = {t["id"]: t for t in items}

        rows = []
        today = dt.date.today()
        for t in items:
            tid = t["id"]
            title = t.get("title") or t.get("text") or ""
            parent_id = t.get("parent_task") or t.get("parent_id")
            if parent_id:
                title = "    " + title
            # aunque list_open_tasks devuelve "open", lo dejo robusto:
            done = (t.get("status") == "done")
            cancelled = (t.get("status") == "cancelled")
            kind = t.get("kind") or "todo"
            recurrence = t.get("recurrence")  # si tienes este campo
            tags = []

            # Vencimiento -> tag
            due = t.get("due_date") or t.get("due")
            if due:
                try:
                    d = dt.date.fromisoformat(str(due)[:10])
                    if d < today and not done:
                        tags.append(("Vencida", "#B00020"))
                    else:
                        tags.append((f"Vence {d.isoformat()}", "#CBD5E1"))
                    if done:
                        tags.append(("✓", "#10B981"))
                    if cancelled:
                        tags.append(("✗", "#9CA3AF"))
                    if recurrence:
                        tags.append(("Recurrencia", "#F59E0B"))
                except Exception:
                    tags.append((str(due), "#CBD5E1"))

            # Prioridad -> tag
            pri = t.get("priority", 0)
            if pri:
                tags.append((f"P{pri}", "#F59E0B"))

            rows.append({
                "id": tid,
                "text": title,
                "done": done,
                "tags": tags,
            })

        self.task_list.set_tasks(rows)
        return len(items)

    # ---------- callbacks desde el widget ----------
    def _on_toggle_cb(self, task_id: str, done: bool):
        """El controller necesita el dict completo -> usamos el cache."""
        self._last_task_id = task_id
        task = self._tasks_by_id.get(task_id)
        if not task:
            return
        try:
            self.controller.toggle_done(task)
        except Exception as e:
            print("Toggle error:", e)
        finally:
            self.refresh()

    def _on_menu_cb(self, task_id: str):
        self._last_task_id = task_id
        task = self._tasks_by_id.get(task_id)

        # Si tienes un menú del controller, lo llamas aquí:
        if hasattr(self.controller, "open_task_menu"):
            try:
                self.controller.open_task_menu(self.context_id, task or {"id": task_id})
                return
            except Exception as e:
                print("Menu error:", e)

        # Menú simple por defecto
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Editar", command=lambda: self._edit_task(task_id))
        menu.add_command(label="Archivar", command=lambda: self._archive_task(task_id))
        try:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def _on_add_subtask_cb(self, task_id: str):
        self._last_task_id = task_id
        # Tu controller no define subtareas aún; deja hook opcional:
        if hasattr(self.controller, "add_subtask"):
            try:
                self.controller.add_subtask(self.context_id, self._tasks_by_id.get(task_id))
            except Exception as e:
                print("Add subtask error:", e)
            finally:
                self.refresh()

    # ---------- header actions ----------
    def _on_add(self, event=None):
        text = self.entry.get().strip()
        if not text:
            return
        try:
            self.controller.add_task(self.context_id, text)
        except Exception as e:
            print("Add error:", e)
        finally:
            self.entry.delete(0, "end")
            self.refresh()

    # ---------- atajos de teclado ----------
    def _kb_toggle_last(self, event=None):
        if not self._last_task_id:
            return
        # lectura del estado visible y toggle
        row = self.task_list._rows.get(self._last_task_id)
        if not row:
            return
        # no necesitamos 'done' exacto porque el controller hace toggle:
        self._on_toggle_cb(self._last_task_id, not bool(row.var.get()))

    def _kb_archive_last(self, event=None):
        if self._last_task_id:
            self._archive_task(self._last_task_id)

    # ---------- helpers ----------
    def _archive_task(self, task_id: str):
        task = self._tasks_by_id.get(task_id)
        if not task:
            return
        try:
            self.controller.archive(task)
        except Exception as e:
            print("Archive error:", e)
        finally:
            self.refresh()

    def _edit_task(self, task_id: str):
        # Hook opcional si más adelante agregas edición
        if hasattr(self.controller, "edit_task"):
            try:
                self.controller.edit_task(self.context_id, self._tasks_by_id.get(task_id))
            except Exception as e:
                print("Edit error:", e)