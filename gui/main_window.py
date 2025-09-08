import tkinter as tk
from tkinter import ttk, messagebox as mb
import datetime as dt
from ..core.config import SYNC_INTERVAL_MS, TOPMOST, WINDOW_GEOMETRY
from ..controller.app_controller import AppController

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

        # Header: quick add
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(6, 4))
        ttk.Label(header, text="Nueva tarea:").pack(side="left")
        self.entry = ttk.Entry(header)
        self.entry.pack(side="left", fill="x", expand=True, padx=6)
        self.entry.bind("<Return>", self._on_add)
        ttk.Button(header, text="Agregar", command=self._on_add).pack(side="left")

        # Treeview
        cols = ("title", "due", "priority")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=14)
        self.tree.heading("title", text="Tarea")
        self.tree.heading("due", text="Vence")
        self.tree.heading("priority", text="Pri")
        self.tree.column("title", anchor="w", width=400)
        self.tree.column("due", anchor="center", width=90)
        self.tree.column("priority", anchor="center", width=60)
        self.tree.tag_configure("overdue", foreground="#B00020")
        self.tree.pack(fill="both", expand=True)

        # bindings
        self.tree.bind("<Double-1>", self._toggle_done)
        self.tree.bind("<space>", self._toggle_done)
        self.tree.bind("<Delete>", self._archive)

    # ---------- data ----------
    def refresh(self) -> int:
        try:
            items = self.controller.list_open_tasks(self.context_id)
        except Exception as e:
            print("Sync error:", e)
            return 0
        self.tree.delete(*self.tree.get_children(""))
        for t in items:
            due = t.get("due_date") or ""
            tag = ()
            try:
                if due and dt.date.fromisoformat(due[:10]) < dt.date.today():
                    tag = ("overdue",)
            except Exception:
                pass
            self.tree.insert("", "end", iid=t["id"], values=(t.get("title"), due[:10] if due else "", t.get("priority", 0)), tags=tag)
        return len(items)

    # ---------- actions ----------
    def _on_add(self, event=None):
        title = self.entry.get().strip()
        if not title:
            return
        try:
            t = self.controller.add_task(self.context_id, title)
            self.entry.delete(0, "end")
            self.refresh()
        except Exception as e:
            from tkinter import messagebox as mb
            mb.showerror("Crear tarea", f"No se pudo crear la tarea: {e}")

    def _toggle_done(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        task_id = sel[0]
        try:
            # obtener datos mínimos para toggle (status actual)
            # en una versión futura podríamos cachearlos
            for iid in sel:
                task = {"id": iid, "status": "open"}  # asumimos open; el server devuelve nuevo estado
                self.controller.toggle_done(task)
            self.refresh()
        except Exception as e:
            from tkinter import messagebox as mb
            mb.showerror("Actualizar", f"No se pudo actualizar la tarea: {e}")

    def _archive(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        from tkinter import messagebox as mb
        if not mb.askyesno("Archivar", "¿Archivar la tarea seleccionada?"):
            return
        try:
            for iid in sel:
                self.controller.archive({"id": iid})
            self.refresh()
        except Exception as e:
            mb.showerror("Archivar", f"No se pudo archivar la tarea: {e}")