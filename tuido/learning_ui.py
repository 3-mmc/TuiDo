"""Learning-path and skill views, kept separate from the daily desk."""

from datetime import date
import json
from pathlib import Path
import tempfile
import webbrowser

from rich.text import Text
from textual import on
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Label, Static

from .syllabus import KINDS, SyllabusError, load_syllabus
from .visuals import render_path_html

LEVELS = ("Not yet", "Explored", "Practised", "Demonstrated")
COLORS = ("#667d94", "#e5bc72", "#74c5b2")


class ReadingPanel(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, title, text):
        super().__init__()
        self.heading, self.text = title, text

    def compose(self):
        with VerticalScroll(id="dialog"):
            yield Label(Text(self.heading), classes="dialog-title")
            yield Static(Text(self.text))
            yield Button("Close", id="close-reading")

    @on(Button.Pressed)
    def close_panel(self):
        self.dismiss()


class ImportPreview(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, preview):
        super().__init__()
        self.preview = preview

    def compose(self):
        p = self.preview
        with VerticalScroll(id="dialog"):
            yield Label("Import syllabus", classes="dialog-title")
            yield Static(Text(f'{p["action"]}: {p["title"]}\n\n'
                f'{p["activities"]} activities · {p["resources"]} resources · {p["skills"]} skills\n'
                f'{p["new"]} new · {p["retained"]} retained · {p["archived"]} archived\n\n'
                'Matching IDs keep their progress and skill evidence.\n'
                'Removed activities stay in history. Ctrl+Z undoes this import.'))
            with Horizontal(classes="buttons"):
                yield Button("Import", id="confirm-import", variant="primary")
                yield Button("Cancel", id="cancel-import")

    @on(Button.Pressed)
    def pressed(self, event):
        self.dismiss(event.button.id == "confirm-import")

    def action_cancel(self):
        self.dismiss(False)


class LearningUI:
    def action_paths(self):
        self.mode = "paths"
        self.refresh_desk()
        self.query_one("#items").focus()

    def action_skills(self):
        self.mode = "skills"
        self.refresh_desk()
        self.query_one("#items").focus()

    def refresh_learning_list(self):
        paths = self.mode == "paths"
        self.query_one("#library-title", Label).update("Learning paths" if paths else "Skills & topics")
        self.query_one("#add-item", Button).label = "+ Path" if paths else "+ Skill"
        if paths:
            items = self.store.rows("SELECT * FROM paths ORDER BY id")
            rows = []
            for path in items:
                nodes, children, states = self.store.learning_snapshot(path["id"])
                progress = Text(path["title"] + "\n")
                for node_id in children.get(None, []):
                    progress.append(("□", "◧", "■")[states[node_id]] + " ", style=COLORS[states[node_id]])
                rows.append((path["id"], [progress]))
            self.path_id = self.fill("#items", rows, self.path_id)
        else:
            items = self.store.rows("SELECT * FROM skills WHERE active=1 ORDER BY level DESC,id")
            rows = [(s["id"], [Text(s["title"] + "\n") + Text("■ " * s["level"] + "□ " * (3-s["level"]), style="#b7adc9")]) for s in items]
            self.skill_id = self.fill("#items", rows, self.skill_id)
        self.query_one("#items").display = bool(items)
        self.query_one("#library-empty").display = not items
        self.query_one("#library-empty", Static).update("Add a path or import an agent's syllabus." if paths else "Add skills to a path, or import a syllabus with skill milestones.")
        self.query_one("#overview", Static).update(f'{len(items)} {"paths" if paths else "skills"}')

    def refresh_learning_detail(self):
        if self.mode == "skills":
            self.render_skill()
            return
        paths = self.store.rows("SELECT * FROM paths WHERE id=?", (self.path_id,))
        if not paths:
            self.query_one("#detail-title", Label).update("Build your own syllabus")
            self.fill("#syllabus", [])
            self.query_one("#learning-actions").display = False
            self.query_one("#learning-info", Static).update("Import a syllabus from JSON, or add a path and build it here.\nF2 opens your existing book library.")
            return
        path = paths[0]
        self.query_one("#detail-title", Label).update(Text(path["title"]))
        nodes, children, states = self.store.learning_snapshot(self.path_id)
        self.learning_nodes = nodes
        rows = []
        def walk(parent=None, prefix=""):
            descendants = children.get(parent, [])
            for n, node_id in enumerate(descendants):
                node = nodes[node_id]
                branch = "└─ " if n == len(descendants)-1 else "├─ "
                expandable = bool(children.get(node_id))
                marker = "▸" if expandable and node_id in self.collapsed else "▾" if expandable else " "
                text = Text(prefix + branch + marker + " ", style="#667d94")
                text.append(("□", "◧", "■")[states[node_id]] + " ", style=COLORS[states[node_id]])
                text.append(node["title"])
                text.append("  " + node["kind"] + (" · optional" if node["optional"] else ""), style="#8fa5bb")
                rows.append((node_id, [text]))
                if expandable and node_id not in self.collapsed:
                    walk(node_id, prefix + ("   " if n == len(descendants)-1 else "│  "))
        walk()
        self.fill("#syllabus", rows)
        self.query_one("#detail-empty").display = not nodes
        self.query_one("#detail-empty", Static).update("Add your first module or activity below.\nc adds a child to the selected module.")
        self.render_activity_info()

    def unmet_prerequisites(self, node_id):
        nodes, _, states = self.store.learning_snapshot(self.path_id)
        by_uid = {n["uid"]: n for n in nodes.values()}
        missing = []
        current = nodes.get(node_id)
        while current:
            for uid in json.loads(current["requires"]):
                if uid in by_uid and states[by_uid[uid]["id"]] != 2:
                    missing.append(by_uid[uid]["title"])
            current = nodes.get(current["parent_id"])
        return list(dict.fromkeys(missing))

    @on(DataTable.RowHighlighted, "#syllabus")
    def highlighted_activity(self):
        if self.mode == "paths":
            self.render_activity_info()

    def render_activity_info(self):
        node_id = self.row_id(self.query_one("#syllabus", DataTable))
        node = self.learning_nodes.get(node_id)
        if not node:
            self.query_one("#learning-info", Static).update("Enter: expand · Space: mark · p: plan · c: add child · i: details")
            return
        info = Text()
        missing = self.unmet_prerequisites(node_id)
        if missing:
            info.append("Suggested first: " + ", ".join(missing) + "\n", style="#e5bc72")
        if node["notes"]:
            info.append(node["notes"].splitlines()[0][:180] + "\n")
        info.append("Enter: expand / mark · p: plan · i: details · v: diagrams", style="#8fa5bb")
        self.query_one("#learning-info", Static).update(info)

    def activate_activity(self):
        node_id = self.row_id(self.query_one("#syllabus", DataTable))
        if node_id and self.store.rows("SELECT id FROM activities WHERE parent_id=? AND active=1", (node_id,)):
            if node_id in self.collapsed:
                self.collapsed.remove(node_id)
            else:
                self.collapsed.add(node_id)
            self.refresh_detail()
        else:
            self.advance_activity()

    def advance_activity(self):
        node_id = self.row_id(self.query_one("#syllabus", DataTable))
        if node_id:
            try:
                self.store.cycle_activity(node_id)
            except ValueError as exc:
                self.notify(str(exc), severity="warning")
                return
            self.refresh_desk()

    def add_learning_item(self):
        from .app import Form
        if self.mode == "paths":
            def save(values):
                if values:
                    self.path_id = self.store.add_path(values["title"], values["description"])
                    self.refresh_desk()
            self.push_screen(Form("Add a learning path", [("title", "Path title", "", False), ("description", "What do you want to understand or do?", "", True)]), save)
        else:
            paths = self.store.rows("SELECT id,title FROM paths ORDER BY id")
            if not paths:
                self.notify("Add a learning path first.")
                return
            def save(values):
                if values:
                    self.skill_id = self.store.add_skill(values["path"], values["title"])
                    self.refresh_desk()
            self.push_screen(Form("Add a skill or topic", [("title", "Skill", "", False)], choices={"path": ("Learning path", [(p["title"], p["id"]) for p in paths], paths[0]["id"])}), save)

    def add_activity(self, child=False):
        from .app import Form
        if self.mode != "paths" or self.path_id is None:
            return
        parent = self.row_id(self.query_one("#syllabus", DataTable)) if child else None
        if parent and self.learning_nodes[parent]["kind"] != "module":
            self.notify("Select a module to add a child. Use + Activity for a top-level item.")
            return
        chapters = self.store.rows("SELECT c.id,c.title,b.title AS book FROM chapters c JOIN books b ON b.id=c.book_id ORDER BY b.id,c.position,c.id")
        def validate(values):
            if values["chapter"] and values["kind"] not in {"read", "exercise"}:
                raise ValueError("A linked chapter needs the Read or Exercise activity type.")
            if values["url"]:
                from urllib.parse import urlsplit
                if urlsplit(values["url"]).scheme not in {"http", "https"} or not urlsplit(values["url"]).netloc:
                    raise ValueError("Resource links must use http or https.")
        def save(values):
            if values:
                self.store.add_activity(self.path_id, values["title"], values["kind"], parent, values["notes"], values["optional"], values["chapter"] or None, values["url"])
                if parent:
                    self.collapsed.discard(parent)
                self.refresh_desk()
        self.push_screen(Form("Add an activity" if not parent else "Add an activity inside this module",
            [("title", "Title", "", False), ("notes", "Notes or instructions", "", True), ("url", "Resource link (optional)", "", False)],
            choices={"kind": ("Activity type", [(k.capitalize(), k) for k in sorted(KINDS)], "module" if not parent else "read"),
                     "optional": ("Required or optional", [("Required", False), ("Optional", True)], False),
                     "chapter": ("Link a Library chapter (optional)", [("No chapter", 0)] + [(f'{c["book"]} — {c["title"]}', c["id"]) for c in chapters], 0)}, validator=validate), save)

    def action_child(self):
        self.add_activity(child=True)

    def action_continue(self):
        if self.mode != "paths" or self.path_id is None:
            return
        nodes, children, states = self.store.learning_snapshot(self.path_id)
        def search(parent=None, optional=False):
            for node_id in children.get(parent, []):
                node = nodes[node_id]
                if optional or node["optional"]:
                    continue
                if children.get(node_id):
                    found = search(node_id)
                    if found:
                        return found
                elif states[node_id] != 2 and not self.unmet_prerequisites(node_id):
                    return node_id
            return None
        next_id = search()
        if not next_id:
            self.status("No unfinished required activity is ready. Review optional work or prerequisites.")
            return
        parent = nodes[next_id]["parent_id"]
        while parent:
            self.collapsed.discard(parent)
            parent = nodes[parent]["parent_id"]
        self.refresh_detail()
        table = self.query_one("#syllabus", DataTable)
        index = list(table.rows).index(next(k for k in table.rows if k.value == str(next_id)))
        table.move_cursor(row=index)
        table.focus()

    def plan_activity(self):
        from .app import Form
        node_id = self.row_id(self.query_one("#syllabus", DataTable))
        if not node_id:
            return
        node = self.learning_nodes[node_id]
        if self.store.rows("SELECT id FROM activities WHERE parent_id=? AND active=1", (node_id,)):
            self.notify("Choose an individual activity inside the module to plan.")
            return
        def save(values):
            if values:
                self.store.add_bullet(date.today().isoformat(), values["title"], habit_id=values["habit_id"], activity_id=node_id)
                self.journal_day = date.today()
                self.today_override = True
                self.apply_width(self.size.width)
                self.refresh_journal()
                self.status("Planned for today. Completing this bullet updates the syllabus.")
        self.push_screen(Form("Plan an activity", [("title", "Task", node["title"], False)], habits=self.store.rows("SELECT * FROM habits ORDER BY id")), save)

    def action_import(self):
        from .app import Form
        def preview(values):
            if not values:
                return
            try:
                data = load_syllabus(values["title"])
                summary = self.store.import_preview(data)
            except (OSError, ValueError, TypeError) as exc:
                self.notify(str(exc), severity="error", timeout=10)
                return
            def apply(confirmed):
                if not confirmed:
                    return
                try:
                    self.path_id = self.store.import_syllabus(data)
                except (SyllabusError, ValueError) as exc:
                    self.notify(str(exc), severity="error", timeout=10)
                    return
                self.mode = "paths"
                self.refresh_desk()
                self.status("Imported syllabus. Ctrl+Z undoes the entire import.")
            self.push_screen(ImportPreview(summary), apply)
        self.push_screen(Form("Open a syllabus file", [("title", "JSON file path", "", False)]), preview)

    def render_skill(self):
        matches = self.store.rows("SELECT * FROM skills WHERE id=? AND active=1", (self.skill_id,))
        self.query_one("#skills-detail").display = bool(matches)
        if not matches:
            self.query_one("#detail-title", Label).update("What you have learned")
            return
        skill = matches[0]
        self.query_one("#detail-title", Label).update(Text(skill["title"]))
        path = self.store.rows("SELECT title FROM paths WHERE id=?", (skill["path_id"],))[0]
        _, _, states = self.store.learning_snapshot(skill["path_id"])
        criteria = self.store.rows("SELECT a.* FROM skill_criteria sc JOIN activities a ON a.id=sc.activity_id WHERE sc.skill_id=? AND a.active=1 ORDER BY a.id", (skill["id"],))
        badge = ("   .---.\n  /  *  \\\n  \\     /\n   '---'\n    / \\\n   /___\\\n" if skill["level"] == 3 else "   .---.\n  /  .  \\\n  \\     /\n   '---'\n")
        text = Text(badge, style="#b7adc9")
        text.append("\n" + LEVELS[skill["level"]] + "\n", style="#a6dace")
        text.append(path["title"] + "\n\nSuggested evidence\n", style="#8fa5bb")
        for criterion in criteria:
            state = states.get(criterion["id"], 0)
            text.append(("□", "◧", "■")[state] + " " + criterion["title"] + "\n", style=COLORS[state])
        if not criteria:
            text.append("Record what you can explain, solve, or make.\n")
        text.append("\nYour evidence\n", style="#8fa5bb")
        text.append(skill["evidence"] or "No evidence recorded yet.")
        text.append("\n\nYou choose the level. Completing readings never automatically awards demonstrated skill.", style="#8fa5bb")
        self.query_one("#skill-description", Static).update(text)

    def edit_skill(self):
        from .app import Form
        if self.mode != "skills" or self.skill_id is None:
            return
        skill = self.store.rows("SELECT * FROM skills WHERE id=?", (self.skill_id,))[0]
        def validate(values):
            if values["level"] == 3 and not values["evidence"].strip():
                raise ValueError("Record evidence before marking this skill demonstrated.")
        def save(values):
            if values:
                self.store.save_skill(skill["id"], values["level"], values["evidence"])
                self.refresh_desk()
        self.push_screen(Form("Record skill progress", [("evidence", "Evidence: notes, solutions, a project, or a link", skill["evidence"], True)],
            choices={"level": ("Your assessment", [(label, level) for level, label in enumerate(LEVELS)], skill["level"])}, validator=validate), save)

    def action_inspect(self):
        if self.mode == "skills":
            self.edit_skill()
        elif self.mode == "paths" and self.path_id:
            node_id = self.row_id(self.query_one("#syllabus", DataTable)) if getattr(self.focused, "id", None) == "syllabus" else None
            node = self.learning_nodes.get(node_id)
            if node:
                content = node["notes"]
                if node["resource_uid"]:
                    resource = self.store.rows("SELECT * FROM resources WHERE uid=?", (node["resource_uid"],))[0]
                    content += "\n\n" + resource["title"] + "\n" + resource["url"]
                missing = self.unmet_prerequisites(node_id)
                if missing:
                    content += "\n\nSuggested first: " + ", ".join(missing)
                content += "\n\n" + node["ascii_art"]
                if node["mermaid"]:
                    content += "\n\nMermaid source (v opens the rendered preview)\n" + node["mermaid"]
                self.push_screen(ReadingPanel(node["title"], content.strip() or "No additional notes."))
            else:
                path = self.store.rows("SELECT * FROM paths WHERE id=?", (self.path_id,))[0]
                self.push_screen(ReadingPanel(path["title"], path["description"] + "\n\n" + path["ascii_art"]))

    def action_visual(self):
        if self.mode != "paths" or not self.path_id:
            return
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".html", prefix="tuido-syllabus-", delete=False) as output:
            output.write(render_path_html(self.store, self.path_id))
            preview = Path(output.name)
        opened = webbrowser.open(preview.as_uri())
        self.status(f'Preview {"opened" if opened else "saved"}: {preview}')
