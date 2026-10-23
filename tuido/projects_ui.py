"""Projects, subtasks, and repeating chores, plus shelf and focus controls."""

from datetime import date

from rich.text import Text
from textual import on
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Label, Static

from .projects import REPEATS

COLORS = ("#667d94", "#e5bc72", "#74c5b2")
PIN = "★ "
SHORT_REPEATS = {1: "daily", 2: "2 days", 3: "3 days", 7: "weekly", 14: "2 weeks", 30: "monthly"}


def repeat_label(task, today):
    """Freshness, not deadlines: when it was last done and how often it comes round."""
    if not task["every_days"]:
        return ""
    every = SHORT_REPEATS.get(task["every_days"], f'{task["every_days"]} days')
    if not task["last_done"]:
        return f"↻ {every}"
    days = (today - date.fromisoformat(task["last_done"])).days
    return f"↻ {every} · {'today' if days == 0 else f'{days}d ago'}"


class ShelfManager(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Close"), ("r", "rename", "Rename"), ("delete", "delete", "Delete")]

    def compose(self):
        with VerticalScroll(id="dialog"):
            yield Label("Shelves", classes="dialog-title")
            yield Static("Shelves group anything in any tab: books, habits, paths, skills, projects.\n"
                         "Deleting a shelf leaves its items in place, unshelved.")
            yield DataTable(id="shelf-list", cursor_type="row", show_header=False)
            yield Static("", id="shelf-empty", classes="empty")
            with Horizontal(classes="buttons"):
                yield Button("+ Shelf", id="add-shelf", variant="primary")
                yield Button("Rename", id="rename-shelf")
                yield Button("Delete", id="delete-shelf")
            yield Button("Close", id="close-shelves")

    def on_mount(self):
        self.query_one("#shelf-list", DataTable).add_column("Shelf")
        self.reload()
        self.query_one("#shelf-list").focus()

    def reload(self):
        table = self.query_one("#shelf-list", DataTable)
        table.clear()
        shelves = self.app.store.shelves()
        for shelf in shelves:
            table.add_row(Text(shelf["title"]), key=str(shelf["id"]))
        table.display = bool(shelves)
        self.query_one("#shelf-empty", Static).update("No shelves yet. Add one, or press s on any item.")
        self.query_one("#shelf-empty").display = not shelves
        self.query_one("#rename-shelf").disabled = self.query_one("#delete-shelf").disabled = not shelves

    def selected(self):
        return self.app.row_id(self.query_one("#shelf-list", DataTable))

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        {"add-shelf": self.add, "rename-shelf": self.action_rename, "delete-shelf": self.action_delete,
         "close-shelves": self.dismiss}[event.button.id]()

    def add(self):
        from .app import Form
        def save(values):
            if values:
                self.app.store.add_shelf(values["title"])
                self.reload()
        self.app.push_screen(Form("Add a shelf", [("title", "Shelf name, e.g. Home, Uni, Languages", "", False)]), save)

    def action_rename(self):
        from .app import Form
        shelf_id = self.selected()
        if shelf_id is None:
            return
        title = self.app.store.rows("SELECT title FROM shelves WHERE id=?", (shelf_id,))[0]["title"]
        def save(values):
            if values:
                self.app.store.rename("shelves", shelf_id, values["title"])
                self.reload()
        self.app.push_screen(Form("Rename shelf", [("title", "New name", title, False)], select_title=True), save)

    def action_delete(self):
        if (shelf_id := self.selected()) is not None:
            self.app.store.delete("shelves", shelf_id)
            self.reload()


class ProjectsUI:
    def action_projects(self):
        self.mode = "projects"
        self.refresh_desk()
        self.query_one("#items").focus()

    # Shelves and focus, shared by every sidebar.
    def view_label(self):
        view = self.store.view()
        parts = ["★ focus"] if view["focus"] else []
        if view["shelf"]:
            parts.append(self.store.rows("SELECT title FROM shelves WHERE id=?", (view["shelf"],))[0]["title"])
        return " · ".join(parts)

    def sidebar_title(self, title):
        """Mark a filtered list; the navigation bar names the full view."""
        view = self.store.view()
        return Text(title + (" ★" if view["focus"] else "") + (" ·" if view["shelf"] else ""))

    def overview(self, text):
        self.query_one("#overview", Static).update(Text(f"{label}  ·  {text}" if (label := self.view_label()) else text))

    def empty_sidebar(self, message):
        """Explain a filtered-out list rather than suggesting it is empty."""
        table = "skills" if self.mode == "skills" else self.mode
        if self.store.sidebar_items(table, filtered=False) and (label := self.view_label()):
            return f"Nothing here for {label}.\n* pins the selected item. f shows everything; ⋯ changes the shelf."
        return message

    def pin_title(self, row):
        return PIN + row["title"] if row.get("pinned") else row["title"]

    def action_previews(self):
        if self.mode not in self.store.PREVIEWS:
            return
        shown = not self.store.previews(self.mode)
        self.store.set_previews(self.mode, shown)
        self.refresh_desk()
        what = "next steps" if self.mode == "projects" else "notes"
        self.status(f"Showing {what} under each item. d hides them." if shown else f"Hiding {what}. d shows them again.")

    def action_focus_mode(self):
        focus = not self.store.view()["focus"]
        self.store.set_view(focus=focus)
        self.refresh_desk()
        self.status("Focus: showing pinned items only. f shows everything again." if focus
                    else "Showing everything. f returns to your pinned focus.")

    def sidebar_record(self):
        table = self.query_one("#items", DataTable)
        item_id = self.row_id(table) if table.display else None
        return self.mode, item_id

    def action_pin(self):
        table, item_id = self.sidebar_record()
        if item_id is None:
            self.status("Select an item in the left list to pin it.")
            return
        pinned = self.store.toggle_pin(table, item_id)
        self.refresh_desk()
        if pinned:
            self.status("Pinned. f shows only pinned items in every tab.")
        else:
            self.status("Unpinned" + (" and hidden from focus. f shows everything." if self.store.view()["focus"] else "."))

    def action_shelve(self):
        from .app import Form
        table, item_id = self.sidebar_record()
        if item_id is None:
            self.status("Select an item in the left list to put it on a shelf.")
            return
        item = self.store.rows(f"SELECT * FROM {table} WHERE id=?", (item_id,))[0]
        shelves = [("No shelf", 0)] + [(s["title"], s["id"]) for s in self.store.shelves()]
        def save(values):
            if values:
                self.store.set_shelf(table, item_id, values["shelf"], values["new-shelf"])
                self.refresh_desk()
                self.status("Shelved. ⋯ shows one shelf at a time; Ctrl+Z undoes this.")
        self.push_screen(Form(f'Shelf for {item["title"]}', [("new-shelf", "…or name a new shelf", "", False)],
                              choices={"shelf": ("Shelf", shelves, item["shelf_id"] or 0)}), save)

    def manage_shelves(self):
        self.push_screen(ShelfManager(), lambda _: self.refresh_desk())

    # Projects
    def refresh_project_list(self):
        self.query_one("#library-title", Label).update(self.sidebar_title("Projects"))
        self.query_one("#add-item", Button).label = "+ Project"
        items = self.store.sidebar_items("projects")
        previews = self.store.previews("projects")
        today = date.today()
        rows = []
        for project in items:
            nodes, children, states = self.store.project_snapshot(project["id"], today)
            text = Text(self.pin_title(project) + "\n")
            for task_id in [t for t in children.get(None, []) if not nodes[t]["every_days"]][:24]:
                text.append(("□", "◧", "■")[states[task_id]] + " ", style=COLORS[states[task_id]])
            ready = sum(1 for t in nodes.values() if t["every_days"] and states[t["id"]] != 2)
            if ready:
                text.append(f"↻ {ready} ready ", style="#b7adc9")
            if previews and (next_id := self.store.next_task(project["id"])):
                text.append("\n→ " + nodes[next_id]["title"], style="#8fa5bb")
            rows.append((project["id"], [text]))
        self.project_id = self.fill("#items", rows, self.project_id)
        self.query_one("#items").display = bool(items)
        self.query_one("#library-empty").display = not items
        self.query_one("#library-empty", Static).update(self.empty_sidebar(
            "Add a project: something long-term like a thesis, or an ongoing area like Home for chores."))
        self.overview(f"{len(items)} projects")

    def refresh_project_detail(self):
        projects = self.store.rows("SELECT * FROM projects WHERE id=?", (self.project_id,))
        if not projects:
            self.query_one("#detail-title", Label).update("Projects and chores")
            self.fill("#tasks", [])
            self.query_one("#project-actions").display = False
            self.query_one("#project-info", Static).update(
                "A project holds steps and subtasks. Chores repeat: they rest after you do them,\n"
                "then quietly come back round. Nothing is ever overdue.")
            return
        self.query_one("#detail-title", Label).update(Text(projects[0]["title"]))
        today = date.today()
        nodes, children, states = self.store.project_snapshot(self.project_id, today)
        self.task_nodes = nodes
        rows = []
        def walk(parent=None, prefix=""):
            kids = children.get(parent, [])
            for n, task_id in enumerate(kids):
                task = nodes[task_id]
                last = n == len(kids) - 1
                expandable = bool(children.get(task_id))
                marker = "▸" if expandable and task_id in self.collapsed_tasks else "▾" if expandable else " "
                text = Text(prefix + ("└─ " if last else "├─ ") + marker + " ", style="#667d94")
                text.append(("□", "◧", "■")[states[task_id]] + " ", style=COLORS[states[task_id]])
                text.append(task["title"])
                if expandable:
                    leaves = [t for t in self.leaves(children, task_id)]
                    side = f"{sum(states[t] == 2 for t in leaves)}/{len(leaves)}"
                else:
                    side = repeat_label(task, today)
                rows.append((task_id, [text, Text(side, style="#8fa5bb", justify="right")]))
                if expandable and task_id not in self.collapsed_tasks:
                    walk(task_id, prefix + ("   " if last else "│  "))
        walk()
        self.fill("#tasks", rows)
        self.query_one("#detail-empty").display = not nodes
        self.query_one("#detail-empty", Static).update(
            "Add a first step below. Small is fine: \"open the folder\" counts.\nc adds a subtask to the selected step.")
        self.render_task_info()

    @staticmethod
    def leaves(children, task_id):
        for kid in children.get(task_id, []):
            if children.get(kid):
                yield from ProjectsUI.leaves(children, kid)
            else:
                yield kid

    def render_task_info(self):
        task = self.task_nodes.get(self.row_id(self.query_one("#tasks", DataTable)))
        info = Text()
        if task:
            if task["every_days"]:
                info.append("Repeating chore. It rests after you do it, then comes back round.\n", style="#b7adc9")
            if task["notes"]:
                info.append(task["notes"].splitlines()[0][:180] + "\n")
        info.append("Enter: open / mark · c: subtask · p: plan today · n: next step · i: notes", style="#8fa5bb")
        self.query_one("#project-info", Static).update(info)

    @on(DataTable.RowHighlighted, "#tasks")
    def highlighted_task(self):
        if self.mode == "projects":
            self.render_task_info()

    def activate_task(self):
        task_id = self.row_id(self.query_one("#tasks", DataTable))
        if task_id and self.store.rows("SELECT id FROM project_tasks WHERE parent_id=? LIMIT 1", (task_id,)):
            self.collapsed_tasks ^= {task_id}
            self.refresh_detail()
        else:
            self.advance_task()

    def advance_task(self):
        task_id = self.row_id(self.query_one("#tasks", DataTable))
        if not task_id:
            return
        try:
            changed = self.store.cycle_task(task_id)
        except ValueError as exc:
            self.notify(str(exc), severity="warning")
            return
        if not changed:
            self.status("Already done recently; it will come back round. Ctrl+Z undoes a mistaken check.")
        self.refresh_desk()

    def add_project(self):
        from .app import Form
        def save(values):
            if values:
                self.project_id = self.store.add_project(values["title"], values["notes"])
                self.store.adopt_view("projects", self.project_id)
                self.refresh_desk()
        self.push_screen(Form("Add a project", [("title", "Project or area", "", False),
                                                ("notes", "Why it matters, or what done looks like (optional)", "", True)]), save)

    def task_form(self, heading, task, save):
        from .app import Form
        self.push_screen(Form(heading, [("title", "Step", task["title"], False), ("notes", "Notes (optional)", task["notes"], True)],
                              choices={"repeat": ("Repeats (for chores like laundry)", [(label, days or 0) for days, label in REPEATS],
                                                  task["every_days"] or 0)}), save)

    def add_task(self, child=False):
        if self.mode != "projects" or self.project_id is None:
            return
        parent = self.row_id(self.query_one("#tasks", DataTable)) if child else None
        if child and parent is None:
            self.status("Select a step first; c adds a subtask inside it.")
            return
        project_id = self.project_id
        def save(values):
            if values:
                self.store.add_task(project_id, values["title"], parent, values["notes"], values["repeat"] or None)
                self.collapsed_tasks.discard(parent)
                self.refresh_desk()
        self.task_form("Add a subtask" if parent else "Add a step", {"title": "", "notes": "", "every_days": None}, save)

    def edit_task(self):
        from .app import Form
        if getattr(self.focused, "id", None) == "tasks" and (task_id := self.row_id(self.query_one("#tasks", DataTable))):
            task = self.store.rows("SELECT * FROM project_tasks WHERE id=?", (task_id,))[0]
            def save(values):
                if values:
                    self.store.edit_task(task_id, values["title"], values["notes"], values["repeat"] or None)
                    self.refresh_desk()
            self.task_form("Edit step", task, save)
        elif self.project_id is not None:
            project = self.store.rows("SELECT * FROM projects WHERE id=?", (self.project_id,))[0]
            def save(values):
                if values:
                    self.store.edit_project(project["id"], values["title"], values["notes"])
                    self.refresh_desk()
            self.push_screen(Form("Edit project", [("title", "Project or area", project["title"], False),
                                                   ("notes", "Why it matters, or what done looks like", project["notes"], True)]), save)

    def next_step(self):
        if self.project_id is None:
            return
        next_id = self.store.next_task(self.project_id)
        if not next_id:
            self.status("No unfinished one-off steps here. Add one, or rest.")
            return
        nodes, _, _ = self.store.project_snapshot(self.project_id)
        parent = nodes[next_id]["parent_id"]
        while parent:
            self.collapsed_tasks.discard(parent)
            parent = nodes[parent]["parent_id"]
        self.refresh_detail()
        table = self.query_one("#tasks", DataTable)
        table.move_cursor(row=[k.value for k in table.rows].index(str(next_id)))
        table.focus()

    def plan_task(self):
        from .app import Form
        task_id = self.row_id(self.query_one("#tasks", DataTable))
        if not task_id:
            return
        if self.store.rows("SELECT id FROM project_tasks WHERE parent_id=? LIMIT 1", (task_id,)):
            self.notify("Choose one subtask to plan; the whole branch is too big for one bullet.")
            return
        task = self.task_nodes[task_id]
        def save(values):
            if values:
                self.store.add_bullet(date.today().isoformat(), values["title"], habit_id=values["habit_id"], project_task_id=task_id)
                self.journal_day = date.today()
                self.today_override = True
                self.apply_width(self.size.width)
                self.refresh_desk()
                self.status("Planned for today. Completing the bullet checks off this step.")
        self.push_screen(Form("Plan a step for today", [("title", "Task", task["title"], False)],
                              habits=self.store.rows("SELECT * FROM habits ORDER BY id")), save)

    def move_task(self, direction):
        task_id = self.row_id(self.query_one("#tasks", DataTable))
        if task_id and self.store.move_task(task_id, direction):
            self.refresh_detail()
            self.query_one("#tasks").focus()
        elif task_id:
            self.status("Already at the edge of this group.")

    def indent_task(self, outdent=False):
        task_id = self.row_id(self.query_one("#tasks", DataTable))
        if not task_id:
            return
        moved = self.store.outdent_task(task_id) if outdent else self.store.indent_task(task_id)
        if moved:
            if not outdent:
                self.collapsed_tasks.discard(moved)
            self.refresh_detail()
            self.query_one("#tasks").focus()
        else:
            self.status("Already at the top level." if outdent else "Nothing above to nest it under.")

    # Ideas: not commitments. Jot freely; take one up when it calls to you.
    def action_ideas(self):
        self.mode = "ideas"
        self.refresh_desk()
        self.query_one("#items").focus()

    def refresh_idea_list(self):
        self.query_one("#library-title", Label).update(self.sidebar_title("Ideas"))
        self.query_one("#add-item", Button).label = "+ Idea"
        items = self.store.sidebar_items("ideas")
        previews = self.store.previews("ideas")
        rows = []
        for idea in items:
            text = Text(self.pin_title(idea), style="#8296aa" if idea["taken_day"] else "")
            if previews and idea["notes"]:
                text.append("\n" + idea["notes"].splitlines()[0][:70], style="#8fa5bb")
            if idea["taken_day"]:
                text.append("\n→ taken up", style="#74c5b2")
            rows.append((idea["id"], [text]))
        self.idea_id = self.fill("#items", rows, self.idea_id)
        self.query_one("#items").display = bool(items)
        self.query_one("#library-empty").display = not items
        self.query_one("#library-empty", Static).update(self.empty_sidebar(
            "A place for maybes. Jot an idea; it asks nothing of you until you take it up."))
        self.overview(f"{len(items)} ideas")

    def refresh_idea_detail(self):
        ideas = self.store.rows("SELECT * FROM ideas WHERE id=?", (self.idea_id,))
        self.query_one("#idea-actions").display = bool(ideas)
        if not ideas:
            self.query_one("#detail-title", Label).update("Ideas")
            self.query_one("#idea-notes", Static).update(Text(
                "Ideas aren't to-dos. Keep them here so they stop circling,\n"
                "and take one up as a project or a step when you feel like it.", style="#8fa5bb"))
            return
        idea = ideas[0]
        self.query_one("#detail-title", Label).update(Text(idea["title"]))
        text = Text(idea["notes"] or "No notes yet. Enter or i adds some.")
        text.append(f'\n\nJotted {idea["created"]}', style="#8fa5bb")
        if idea["taken_day"]:
            project = self.store.rows("SELECT title FROM projects WHERE id=?", (idea["project_id"],))
            text.append(f'\nTaken up {idea["taken_day"]}' + (f' in {project[0]["title"]} (F5)' if project else ""), style="#74c5b2")
        self.query_one("#idea-notes", Static).update(text)

    def add_idea(self):
        from .app import Form
        def save(values):
            if values:
                self.idea_id = self.store.add_idea(values["title"], values["notes"])
                self.store.adopt_view("ideas", self.idea_id)
                self.refresh_desk()
        self.push_screen(Form("Jot an idea", [("title", "Idea", "", False), ("notes", "Notes (optional)", "", True)]), save)

    def edit_idea(self):
        from .app import Form
        if self.idea_id is None:
            return
        idea = self.store.rows("SELECT * FROM ideas WHERE id=?", (self.idea_id,))[0]
        def save(values):
            if values:
                self.store.edit_idea(idea["id"], values["title"], values["notes"])
                self.refresh_desk()
        self.push_screen(Form("Edit idea", [("title", "Idea", idea["title"], False), ("notes", "Notes", idea["notes"], True)]), save)

    def take_up_idea(self, as_step=False):
        from .app import Form
        if self.idea_id is None:
            return
        idea_id = self.idea_id
        if not as_step:
            self.project_id = self.store.take_up_idea(idea_id)
            self.refresh_desk()
            self.status("Started as a project. F5 shows it; Ctrl+Z undoes this.")
            return
        projects = self.store.rows("SELECT id,title FROM projects ORDER BY pinned DESC,title")
        if not projects:
            self.notify("No projects yet. Start this idea as a project instead.")
            return
        def save(values):
            if values:
                self.project_id = self.store.take_up_idea(idea_id, values["project"])
                self.refresh_desk()
                self.status("Added as a step. F5 shows it; Ctrl+Z undoes this.")
        self.push_screen(Form("Add idea as a step", [], choices={"project": ("Project", [(p["title"], p["id"]) for p in projects], projects[0]["id"])}), save)
