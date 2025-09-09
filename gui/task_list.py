"""
Scrollable Task List widget for Tkinter
--------------------------------------
A drop-in replacement for a Treeview-based task list. It renders each task as
its own row (a Frame) inside a scrollable Canvas, with:
- a Checkbutton to mark completion
- the task text (wrapping/expand)
- optional colored tags (labels)
- an overflow/menu button (⋮) and a "+" button for quick subtask add

Integration notes (MVC-friendly):
- The widget is view-only state. All state changes are driven by the controller
  via callbacks. You pass callbacks in the constructor.
- Use `set_tasks()` with a list of task dicts to render.
- Use `update_task()`, `remove_task()`, `insert_task()` to modify.
- Bind to virtual events if you prefer: <<TaskToggle>>, <<TaskMenu>>, <<TaskAddSubtask>>

Author: ChatGPT (DSN project)
Tested: Python 3.12+, Tkinter (ttk)
"""
from __future__ import annotations
from typing import Callable, Dict, List, Optional, Tuple
import tkinter as tk
from tkinter import ttk

class TaskRow(ttk.Frame):
    """A single task row with checkbox, text, colored tags, and action buttons."""
    def __init__(
        self,
        master,
        task_id: str,
        text: str,
        done: bool = False,
        tags: Optional[List[Tuple[str, str]]] = None,  # [(label, hex_color)]
        on_toggle: Optional[Callable[[str, bool], None]] = None,
        on_menu: Optional[Callable[[str], None]] = None,
        on_add_subtask: Optional[Callable[[str], None]] = None,
        wrap: int = 600,
    ):
        super().__init__(master)
        self.task_id = task_id
        self._on_toggle = on_toggle
        self._on_menu = on_menu
        self._on_add_subtask = on_add_subtask
        self.var = tk.BooleanVar(value=done)

        self.columnconfigure(2, weight=1)

        # Checkbox
        self.chk = ttk.Checkbutton(self, variable=self.var, command=self._toggle)
        self.chk.grid(row=0, column=0, padx=(8, 6), pady=4, sticky="w")

        # Text label (wrapping)
        self.lbl = ttk.Label(self, text=text, wraplength=wrap, anchor="w", justify="left")
        self.lbl.grid(row=0, column=2, sticky="we")

        # Tag container
        self.tag_container = ttk.Frame(self)
        self.tag_container.grid(row=1, column=2, sticky="w", pady=(2, 4))

        # Actions (⋮ and +)
        self.menu_btn = ttk.Button(self, text="⋮", width=2, command=self._menu)
        self.menu_btn.grid(row=0, column=3, padx=(6, 4))
        self.add_btn = ttk.Button(self, text="+", width=2, command=self._add_subtask)
        self.add_btn.grid(row=0, column=4, padx=(0, 8))

        self._render_tags(tags or [])
        self._apply_done_style(done)

    # --- Public API ---
    def set_text(self, text: str):
        self.lbl.configure(text=text)

    def set_done(self, done: bool):
        self.var.set(done)
        self._apply_done_style(done)

    def set_tags(self, tags: List[Tuple[str, str]]):
        for child in self.tag_container.winfo_children():
            child.destroy()
        self._render_tags(tags)

    # --- Internals ---
    def _render_tags(self, tags: List[Tuple[str, str]]):
        for i, (label, color) in enumerate(tags):
            # Use tk.Label to allow background color without ttk style plumbing
            tag = tk.Label(
                self.tag_container,
                text=label,
                bg=color,
                fg=_ideal_text_color(color),
                padx=4,
                pady=2,
                borderwidth=0,
                relief="flat",
            )
            tag.pack(side="left", padx=(0, 6))

    def _apply_done_style(self, done: bool):
        if done:
            self.lbl.configure(style="Task.Done.TLabel")
        else:
            self.lbl.configure(style="Task.Normal.TLabel")

    def _toggle(self):
        done = bool(self.var.get())
        self._apply_done_style(done)
        if self._on_toggle:
            self._on_toggle(self.task_id, done)
        self.event_generate("<<TaskToggle>>", when="tail")

    def _menu(self):
        if self._on_menu:
            self._on_menu(self.task_id)
        self.event_generate("<<TaskMenu>>", when="tail")

    def _add_subtask(self):
        if self._on_add_subtask:
            self._on_add_subtask(self.task_id)
        self.event_generate("<<TaskAddSubtask>>", when="tail")


class ScrollableTaskList(ttk.Frame):
    """Canvas + interior Frame pattern with proper mousewheel support and API."""
    def __init__(
        self,
        master,
        on_toggle: Optional[Callable[[str, bool], None]] = None,
        on_menu: Optional[Callable[[str], None]] = None,
        on_add_subtask: Optional[Callable[[str], None]] = None,
        row_wrap: int = 600,
        row_padding: Tuple[int, int] = (2, 2),
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self._on_toggle = on_toggle
        self._on_menu = on_menu
        self._on_add_subtask = on_add_subtask
        self._row_wrap = row_wrap
        self._row_padding = row_padding
        self._rows: Dict[str, TaskRow] = {}

        # --- styles ---
        style = ttk.Style(self)
        style.configure("Task.Normal.TLabel")
        style.configure("Task.Done.TLabel", foreground="#888888")

        # --- layout ---
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        # Interior frame inside canvas
        self.interior = ttk.Frame(self.canvas)
        self._win_id = self.canvas.create_window(0, 0, window=self.interior, anchor="nw")

        # Resize/wrapping sync
        self.interior.bind("<Configure>", self._on_interior_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Mousewheel support (Windows/macOS/Linux)
        self._bind_mousewheel(self.canvas)
        self._bind_mousewheel(self.interior)

    # --- Public API ---
    def set_tasks(self, tasks: List[Dict]):
        """Replace all tasks. Each task dict: {
            'id': str,
            'text': str,
            'done': bool,
            'tags': List[Tuple[label, color]]
        }
        """
        # clear
        for row in list(self._rows.values()):
            row.destroy()
        self._rows.clear()

        for task in tasks:
            self.insert_task(
                task_id=task["id"],
                text=task.get("text", ""),
                done=task.get("done", False),
                tags=task.get("tags", []),
            )

        self._repack_rows()

    def insert_task(self, task_id: str, text: str, done: bool = False, tags: Optional[List[Tuple[str, str]]] = None):
        if task_id in self._rows:
            return
        row = TaskRow(
            self.interior,
            task_id=task_id,
            text=text,
            done=done,
            tags=tags or [],
            on_toggle=self._on_toggle,
            on_menu=self._on_menu,
            on_add_subtask=self._on_add_subtask,
            wrap=self._row_wrap,
        )
        self._rows[task_id] = row
        row.grid(sticky="we", padx=(8, 8), pady=self._row_padding)
        self.interior.columnconfigure(0, weight=1)
        self._update_scrollregion()

    def remove_task(self, task_id: str):
        row = self._rows.pop(task_id, None)
        if row:
            row.destroy()
            self._update_scrollregion()

    def update_task(
        self,
        task_id: str,
        *,
        text: Optional[str] = None,
        done: Optional[bool] = None,
        tags: Optional[List[Tuple[str, str]]] = None,
    ):
        row = self._rows.get(task_id)
        if not row:
            return
        if text is not None:
            row.set_text(text)
        if done is not None:
            row.set_done(done)
        if tags is not None:
            row.set_tags(tags)
        self._update_scrollregion()

    def scroll_to_task(self, task_id: str):
        row = self._rows.get(task_id)
        if not row:
            return
        self.canvas.update_idletasks()
        # Ensure row is visible by yview moveto based on row's y
        bbox = self.canvas.bbox(self._win_id)
        if not bbox:
            return
        y = row.winfo_y()
        height = self.interior.winfo_height()
        if height > 0:
            self.canvas.yview_moveto(y / height)

    # --- Internals ---
    def _repack_rows(self):
        for i, row in enumerate(self._rows.values()):
            row.grid_configure(row=i)
        self._update_scrollregion()

    def _update_scrollregion(self):
        self.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_interior_configure(self, _):
        self._update_scrollregion()

    def _on_canvas_configure(self, event):
        # Keep interior width synced to canvas for wrapping
        self.canvas.itemconfigure(self._win_id, width=event.width)
        # Adjust wraplength for labels
        for row in self._rows.values():
            row.lbl.configure(wraplength=event.width - 160)  # some space for buttons

    # Mousewheel helpers
    def _bind_mousewheel(self, widget):
        widget.bind_all("<MouseWheel>", self._on_mousewheel_windows_mac, add="+")
        widget.bind_all("<Button-4>", self._on_mousewheel_linux, add="+")
        widget.bind_all("<Button-5>", self._on_mousewheel_linux, add="+")

    def _on_mousewheel_windows_mac(self, event):
        # On Windows, event.delta is usually +/-120; on macOS it's different.
        delta = int(-1 * (event.delta / 120))
        self.canvas.yview_scroll(delta, "units")

    def _on_mousewheel_linux(self, event):
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")


# --- Utility: pick readable text color for a given bg ---
def _ideal_text_color(bg_hex: str) -> str:
    """Return black or white depending on background brightness."""
    bg_hex = bg_hex.strip().lstrip('#')
    if len(bg_hex) == 3:
        bg_hex = ''.join(c*2 for c in bg_hex)
    try:
        r = int(bg_hex[0:2], 16)
        g = int(bg_hex[2:4], 16)
        b = int(bg_hex[4:6], 16)
    except Exception:
        return "black"
    # Perceived luminance
    luminance = 0.299*r + 0.587*g + 0.114*b
    return "black" if luminance > 186 else "white"









# --- Demo ---
if __name__ == "__main__":
    root = tk.Tk()
    root.title("Scrollable Task List Demo")
    root.geometry("720x480")

    # Controller callbacks
    def on_toggle(task_id: str, done: bool):
        print(f"TOGGLE: {task_id} -> {done}")

    def on_menu(task_id: str):
        print(f"MENU for {task_id}")

    def on_add_subtask(task_id: str):
        print(f"ADD SUBTASK under {task_id}")

    header = ttk.Label(root, text="Tasks", font=("Segoe UI", 16, "bold"))
    header.pack(anchor="w", padx=12, pady=(12, 6))

    task_list = ScrollableTaskList(
        root,
        on_toggle=on_toggle,
        on_menu=on_menu,
        on_add_subtask=on_add_subtask,
    )
    task_list.pack(fill="both", expand=True, padx=12, pady=12)

    # Sample data
    tasks = [
        {
            "id": "t1",
            "text": "Comprar repuestos del pedido #431 y coordinar envío a cliente.",
            "done": False,
            "tags": [("Prioridad", "#EAB308"), ("Cliente", "#38BDF8")],
        },
        {
            "id": "t2",
            "text": "Refactor del módulo de licencias: extraer validador a services. Revisar manejo de errores y logs.",
            "done": True,
            "tags": [("Code", "#22C55E")],
        },
        {
            "id": "t3",
            "text": "Agregar vista de contraste Stock vs Orden en ventana Toplevel, con refresh al cambiar selección en Treeview.",
            "done": False,
            "tags": [("DSN", "#A78BFA"), ("UI", "#F472B6")],
        },
    ]

    task_list.set_tasks(tasks)

    root.mainloop()
