"""The reading desk: a library, its contents, and a daily margin."""

from datetime import date, timedelta
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Footer, Input, Label, Select, Static, TextArea

from .store import Store
from .learning_ui import LearningUI
from .projects_ui import ProjectsUI


class WrappingTable(DataTable):
    """Refit wrapped rows after layout, including when a hidden pane reappears."""

    def on_resize(self):
        self.call_after_refresh(self.refit)

    def refit(self):
        if self.display and self.size.width and hasattr(self, "wrapped_rows"):
            if self.size.width != self.filled_width:
                self.app.fill(f"#{self.id}", self.wrapped_rows)


class Form(ModalScreen[dict | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title, fields, *, textbook=False, habits=None, choices=None, validator=None, select_title=False):
        super().__init__()
        self.heading, self.fields = title, fields
        self.textbook, self.habits = textbook, habits
        self.choices = choices or {}
        self.validator = validator
        self.select_title = select_title

    def on_mount(self):
        if self.select_title:
            field = self.query_one("#title", Input)
            field.focus()
            field.action_select_all()

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            with VerticalScroll(id="form-fields"):
                yield Label(self.heading, classes="dialog-title")
                for name, label, value, multiline in self.fields:
                    yield Label(label)
                    if multiline:
                        yield TextArea(value, id=name)
                    else:
                        yield Input(value, id=name)
                if self.textbook:
                    yield Checkbox("Track exercises separately", id="textbook")
                for name, (label, options, value) in self.choices.items():
                    yield Label(label)
                    yield Select(options, value=value, allow_blank=False, id=name)
                if self.habits is not None:
                    yield Label("Also log 1 unit to a habit when completed (optional)")
                    yield Select([(h["title"], h["id"]) for h in self.habits], prompt="No habit", id="linked-habit")
            yield Static("", id="form-error")
            with Horizontal(classes="buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    @on(Button.Pressed, "#cancel")
    def action_cancel(self):
        self.dismiss(None)

    @on(Button.Pressed, "#save")
    def save(self):
        values = {}
        for name, _, _, multiline in self.fields:
            widget = self.query_one(f"#{name}")
            values[name] = (widget.text if multiline else widget.value).strip()
        if "title" in values and not values["title"]:
            self.query_one("#form-error", Static).update("Enter a name or some text first.")
            return
        try:
            self.validate_numbers(values)
        except ValueError as exc:
            self.query_one("#form-error", Static).update(Text(str(exc)))
            return
        if self.textbook:
            values["textbook"] = self.query_one("#textbook", Checkbox).value
        if self.habits is not None:
            value = self.query_one("#linked-habit", Select).value
            values["habit_id"] = value if isinstance(value, int) else None
        for name in self.choices:
            values[name] = self.query_one(f"#{name}", Select).value
        if self.validator:
            try:
                self.validator(values)
            except ValueError as exc:
                self.query_one("#form-error", Static).update(Text(str(exc)))
                return
        self.dismiss(values)

    def validate_numbers(self, values):
        for name, low, high in (("daily", 1, 1000000), ("weekly", 1, 7)):
            if name in values:
                try:
                    values[name] = int(values[name])
                    if not low <= values[name] <= high:
                        raise ValueError
                except ValueError:
                    raise ValueError(f"{name.capitalize()} goal must be a whole number from {low} to {high}.")

    @on(Input.Submitted)
    def submitted(self):
        self.save()


class HabitForm(Form):
    """Show goal-specific controls and describe the resulting target in plain text."""

    def compose(self):
        fields = {name: (label, value) for name, label, value, _ in self.fields}
        with Vertical(id="dialog"):
            with VerticalScroll(id="form-fields"):
                yield Label(self.heading, classes="dialog-title")
                for name in ("title", "unit"):
                    label, value = fields[name]
                    yield Label(label)
                    yield Input(value, id=name)
                label, options, value = self.choices["goal-period"]
                yield Label(label)
                yield Select(options, value=value, allow_blank=False, id="goal-period")
                yield Label("", id="goal-amount-label")
                yield Input(fields["daily"][1], id="daily", type="integer")
                with Vertical(id="days-per-week"):
                    yield Label("How many days per week? (1–7)")
                    yield Input(fields["weekly"][1], id="weekly", type="integer")
                yield Static("", id="goal-preview")
                label, options, value = self.choices["parent"]
                yield Label(label)
                yield Select(options, value=value, allow_blank=False, id="parent")
                yield Static("Optional: entries also count toward this habit. Both must use the same unit.")
            yield Static("", id="form-error")
            with Horizontal(classes="buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def on_mount(self):
        self.update_goal_ui()
        self.query_one("#title", Input).focus()

    @on(Select.Changed, "#goal-period")
    @on(Input.Changed, "#daily, #weekly, #unit, #title")
    def update_goal_ui(self):
        weekly = self.query_one("#goal-period", Select).value == "week"
        self.query_one("#days-per-week").display = not weekly
        self.query_one("#goal-amount-label", Label).update("Total units per week" if weekly else "Units on each active day")
        self.query_one("#form-error", Static).update("")
        title = self.query_one("#title", Input).value.strip() or "This habit"
        unit = self.query_one("#unit", Input).value.strip() or "sessions"
        amount = self.query_one("#daily", Input).value.strip() or "…"
        days = self.query_one("#weekly", Input).value.strip() or "…"
        description = (f"{title}: {amount} {unit} per week, on any days. No daily minimum."
                       if weekly else f"{title}: {amount} {unit} on each of {days} days per week. You choose the days.")
        self.query_one("#goal-preview", Static).update(Text(description))

    def validate_numbers(self, values):
        weekly = self.query_one("#goal-period", Select).value == "week"
        try:
            values["daily"] = int(values["daily"])
            if not 1 <= values["daily"] <= 1000000:
                raise ValueError
        except ValueError:
            label = "Total units per week" if weekly else "Units on each active day"
            raise ValueError(f"{label} must be a whole number from 1 to 1000000.")
        if weekly:
            # Preserve the daily schedule for switching back, without validating
            # a hidden field or applying it to a weekly total.
            values["weekly"] = next(int(value) for name, _, value, _ in self.fields if name == "weekly")
        else:
            try:
                values["weekly"] = int(values["weekly"])
                if not 1 <= values["weekly"] <= 7:
                    raise ValueError
            except ValueError:
                raise ValueError("Days per week must be a whole number from 1 to 7.")


class SidebarOptions(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, collection, sorts, current, title, can_up, can_down, *, pinned=False, view=None, shelves=(), previews=None):
        super().__init__()
        self.previews = previews
        self.collection, self.sorts, self.current = collection, sorts, current
        self.title, self.can_up, self.can_down = title, can_up, can_down
        self.pinned, self.view, self.shelves = pinned, view or {"focus": False, "shelf": None}, shelves

    def compose(self):
        labels = {"custom": "Custom order", "name": "Name A–Z", "name-desc": "Name Z–A",
                  "oldest": "Oldest first", "newest": "Newest first", "level": "Skill level"}
        with VerticalScroll(id="dialog"):
            yield Label(f"{self.collection.capitalize()} · options", classes="dialog-title")
            yield Label("Sort list")
            yield Select([(labels[key], key) for key in self.sorts], value=self.current,
                         allow_blank=False, id="sidebar-sort")
            yield Static(Text(f"Selected: {self.title}" if self.title else "Select an item to move, pin, or shelve it."))
            with Horizontal(id="sidebar-order"):
                yield Button("↑ Up", id="move-up", disabled=not self.can_up)
                yield Button("↓ Down", id="move-down", disabled=not self.can_down)
                yield Button("☆ Unpin" if self.pinned else "★ Pin", id="pin-item", disabled=not self.title)
                yield Button("Shelf…", id="shelve-item", disabled=not self.title)
            yield Static("Parents move with their children. Children move among siblings."
                         if self.collection == "habits" else "Moving an item saves a custom order.")
            if self.previews is not None:
                yield Checkbox("Show next step under each project" if self.collection == "projects"
                               else "Show notes under each idea", self.previews, id="sidebar-previews")
            yield Label("Show, in every tab")
            with Horizontal(id="sidebar-view"):
                yield Select([("Everything", False), ("★ Focus only", True)], value=self.view["focus"],
                             allow_blank=False, id="view-focus")
                yield Select([("All shelves", 0)] + [(s["title"], s["id"]) for s in self.shelves],
                             value=self.view["shelf"] or 0, allow_blank=False, id="view-shelf")
            with Horizontal(classes="buttons"):
                yield Button("Shelves…", id="manage-shelves")
                yield Button("Close", id="close-options")

    def on_mount(self):
        self.query_one("#sidebar-sort").focus()

    @on(Select.Changed, "#sidebar-sort")
    def choose_sort(self, event):
        event.stop()
        if event.value in self.sorts and event.value != self.current:
            self.dismiss(("sort", event.value))

    @on(Checkbox.Changed, "#sidebar-previews")
    def choose_previews(self, event):
        event.stop()
        self.dismiss(("previews", event.value))

    @on(Select.Changed, "#view-focus")
    def choose_focus(self, event):
        event.stop()
        if event.value != self.view["focus"]:
            self.dismiss(("focus", event.value))

    @on(Select.Changed, "#view-shelf")
    def choose_shelf(self, event):
        event.stop()
        if event.value != (self.view["shelf"] or 0):
            self.dismiss(("view-shelf", event.value))

    @on(Button.Pressed)
    def choose_action(self, event):
        event.stop()
        direction = {"move-up": -1, "move-down": 1}.get(event.button.id)
        if direction:
            self.dismiss(("move", direction))
        else:
            self.dismiss({"pin-item": ("pin", None), "shelve-item": ("shelve", None),
                          "manage-shelves": ("manage", None)}.get(event.button.id))


class Help(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Close"), ("question_mark", "dismiss", "Close")]

    def compose(self):
        with VerticalScroll(id="dialog"):
            yield Label("A place to make steady progress", classes="dialog-title")
            yield Static(
                "Tab / Shift+Tab   Move between columns and controls\n"
                "↑ ↓               Move through books, chapters, or bullets\n"
                "Enter             Select a book; advance chapter; complete bullet\n"
                "Space             Advance chapter; complete bullet\n"
                "e                 Toggle textbook exercises\n"
                "p                 Put the selected chapter in Today\n"
                "a                 Add to the focused column\n"
                "r / Rename button Rename the selected item in that pane\n"
                "Alt+Up/Down       Reorder selected sidebar item or project step\n"
                "Alt+Left/Right    Lift a step out / nest it under the step above\n"
                "Delete            Delete selected item (Ctrl+Z to undo)\n"
                "+ / -             Add / subtract one habit unit on selected date\n"
                "Ctrl+J            Jot a task (prefix '- ' for a note)\n"
                "Ctrl+T            Show / hide the daily pane\n"
                "F1 … F6           Paths / Library / Habits / Skills / Projects / Ideas\n"
                "*                 Pin the selected sidebar item for focus\n"
                "f                 Focus: show only pinned items, in every tab\n"
                "s                 Put the selected sidebar item on a shelf\n"
                "d                 Show / hide idea notes or project next steps\n"
                "Ctrl+O            Preview and import a syllabus JSON file\n"
                "c                 Add a child module item, or a project subtask\n"
                "n                 Continue a path, or jump to a project's next step\n"
                "i / v             Inspect notes (edit a step) / open syllabus diagrams\n"
                "Ctrl+Left/Right   Browse habit and journal dates\n"
                "Ctrl+Y            Carry selected unfinished bullet to today\n"
                "Ctrl+Z            Undo last change (up to 50 this session)\n"
                "Ctrl+Q            Quit\n\n"
                "Reading: □ unstarted → ◧ reading → ■ finished\n"
                "Journal: • task   × done   – note   › carried forward\n\n"
                "Tomorrow starts a fresh page. Older pages stay in history;\n"
                "unfinished tasks move only when you carry them forward.\n\n"
                "Planning a chapter can link it to a habit. Completing the bullet\n"
                "finishes the reading and logs one habit unit in one undoable step.\n"
                "Reopening it keeps that progress; use Undo to reverse the action.\n\n"
                "Projects hold steps and subtasks. Chores repeat: after you do\n"
                "one it rests for its interval, then comes back round. Nothing\n"
                "is ever overdue. Shelves and focus hide everything else.\n"
                "Ideas are maybes, not to-dos: take one up as a project or step.\n\n"
                "Habits support daily amounts or weekly totals on any days.\n"
                "Child habits contribute to their parent. Future entries are plans.\n"
                "Use Edit habit for goals, Set amount for corrections, Date to jump."
            )
            yield Button("Back to the desk", id="close-help")

    @on(Button.Pressed)
    def close_help(self):
        self.dismiss()


class Tuido(LearningUI, ProjectsUI, App):
    TITLE = "Tuido"
    CSS_PATH = "desk.tcss"
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("f1", "paths", "Paths"),
        Binding("f2", "books", "Library"),
        Binding("f3", "habits", "Habits"),
        Binding("f4", "skills", "Skills"),
        Binding("f5", "projects", "Projects"),
        Binding("f6", "ideas", "Ideas", show=False),
        Binding("alt+left", "outdent", "Outdent", show=False),
        Binding("alt+right", "indent", "Indent", show=False),
        Binding("f", "focus_mode", "Focus"),
        Binding("asterisk", "pin", "Pin", show=False),
        Binding("s", "shelve", "Shelf", show=False),
        Binding("d", "previews", "Previews", show=False),
        Binding("ctrl+o", "import", "Import", show=False),
        Binding("i", "inspect", "Details", show=False),
        Binding("v", "visual", "Visuals", show=False),
        Binding("n", "continue", "Continue", show=False),
        Binding("c", "child", "Add child", show=False),
        Binding("ctrl+j", "jot", "Jot"),
        Binding("ctrl+t", "today", "Today"),
        Binding("a", "add", "Add"),
        Binding("space", "advance", "Mark", show=False),
        Binding("e", "exercises", "Exercises", show=False),
        Binding("p", "plan", "Plan", show=False),
        Binding("r", "rename", "Rename"),
        Binding("delete", "delete", "Delete", show=False),
        Binding("plus,equals", "increment", "+ Unit", show=False),
        Binding("minus", "decrement", "− Unit", show=False),
        Binding("ctrl+z", "undo", "Undo"),
        Binding("ctrl+left", "previous_day", "Previous day", show=False),
        Binding("ctrl+right", "next_day", "Next day", show=False),
        Binding("ctrl+y", "migrate", "Carry forward", show=False),
        Binding("alt+up", "move_up", "Move up", show=False),
        Binding("alt+down", "move_down", "Move down", show=False),
        Binding("question_mark", "help", "Help"),
    ]

    def __init__(self, store: Store, *, demo=False):
        super().__init__()
        self.store = store
        self.demo = demo
        self.mode = "paths" if store.rows("SELECT id FROM paths LIMIT 1") or not store.rows("SELECT id FROM books LIMIT 1") else "books"
        self.book_id = None
        self.habit_id = None
        self.path_id = None
        self.skill_id = None
        self.project_id = None
        self.idea_id = None
        self.collapsed = set()
        self.collapsed_tasks = set()
        self.task_nodes = {}
        self.learning_nodes = {}
        self.journal_day = date.today()
        self.last_today = date.today()
        self.today_override = None

    def compose(self):
        with Horizontal(id="masthead"):
            yield Static("[bold]tuido[/bold]  /  a little, often", id="brand")
            yield Static("", id="date")
        with Horizontal(id="navigation"):
            yield Button("Paths", id="show-paths")
            yield Button("Library", id="show-books", variant="primary")
            yield Button("Habits", id="show-habits")
            yield Button("Skills", id="show-skills")
            yield Button("Projects", id="show-projects")
            yield Button("Ideas", id="show-ideas")
            yield Static("", id="overview")
            yield Button("Today", id="show-today")
        with Horizontal(id="desk"):
            with Vertical(id="library", classes="panel"):
                with Horizontal(classes="panel-heading"):
                    yield Label("Books", id="library-title", classes="heading")
                    yield Button("Rename", id="rename-item", disabled=True)
                    yield Button("⋯", id="sidebar-options", tooltip="List options: sort and reorder")
                yield WrappingTable(id="items", cursor_type="row", show_header=False, show_row_labels=False)
                yield Static("", id="library-empty", classes="empty")
                yield Button("+ Book", id="add-item")
                yield Button("Import syllabus", id="import-syllabus")
            with Vertical(id="contents", classes="panel"):
                with Horizontal(classes="panel-heading"):
                    yield Label("Choose a book", id="detail-title", classes="heading")
                    yield Button("Rename", id="rename-detail", disabled=True)
                yield Static("", id="progress")
                yield DataTable(id="chapters", cursor_type="row", show_row_labels=False)
                yield WrappingTable(id="syllabus", cursor_type="row", show_header=False, show_row_labels=False)
                yield WrappingTable(id="tasks", cursor_type="row", show_header=False, show_row_labels=False)
                with VerticalScroll(id="skills-detail"):
                    with Horizontal(id="skill-header"):
                        yield Static("", id="skill-art")
                        yield Static("", id="skill-assessment")
                    yield Static("", id="skill-description")
                    yield Button("Record progress & evidence", id="edit-skill")
                with VerticalScroll(id="habit-detail"):
                    with Horizontal(id="habit-nav", classes="buttons"):
                        yield Button("‹", id="habit-prev")
                        yield Button("Today", id="habit-today")
                        yield Button("›", id="habit-next")
                        yield Button("Date…", id="habit-date")
                    yield Static("", id="habit-summary")
                    with Horizontal(classes="buttons"):
                        yield Button("− 1", id="subtract-unit")
                        yield Button("+ 1 unit", id="add-unit", variant="primary")
                        yield Button("Log amount", id="log-amount")
                    with Horizontal(classes="buttons"):
                        yield Button("Set amount", id="set-amount")
                        yield Button("Edit habit", id="edit-habit")
                    yield Static("", id="heatmap")
                    yield Static("", id="habit-legend")
                yield Static("", id="detail-empty", classes="empty")
                yield Static("", id="detail-hint", classes="hint")
                yield Static("", id="learning-info", classes="hint")
                with Horizontal(id="learning-actions", classes="buttons"):
                    yield Button("+ Activity", id="add-activity")
                    yield Button("Continue", id="continue-path")
                    yield Button("Visuals", id="view-visual")
                yield Static("", id="project-info", classes="hint")
                with Horizontal(id="project-actions", classes="buttons"):
                    yield Button("+ Step", id="add-task")
                    yield Button("+ Subtask", id="add-subtask")
                    yield Button("Next step", id="next-step")
                    yield Button("Plan today", id="plan-task")
                    yield Button("Edit", id="edit-task")
                with VerticalScroll(id="idea-detail"):
                    yield Static("", id="idea-notes")
                with Horizontal(id="idea-actions", classes="buttons"):
                    yield Button("Edit", id="edit-idea")
                    yield Button("Start as project", id="idea-project", variant="primary")
                    yield Button("Add as a step…", id="idea-step")
                with Horizontal(id="chapter-actions", classes="buttons"):
                    yield Button("+ Chapter", id="add-chapter")
                    yield Button("Plan today", id="plan-chapter")
            with Vertical(id="journal", classes="panel"):
                with Horizontal(classes="panel-heading"):
                    yield Label("Today", id="journal-title", classes="heading")
                    yield Button("Rename", id="rename-bullet", disabled=True)
                with Horizontal(id="journal-nav"):
                    yield Button("‹", id="prev-day")
                    yield Button("Today", id="current-day")
                    yield Button("›", id="next-day")
                yield Static("", id="journal-summary")
                yield WrappingTable(id="bullets", cursor_type="row", show_header=False, show_row_labels=False)
                yield Static("", id="journal-empty", classes="empty")
                yield Static("• task   × done   – note\nCtrl+Y carries an old task to today", classes="hint")
                yield Button("+ Jot something", id="jot")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self):
        self.query_one("#items", DataTable).add_column("Item")
        chapters = self.query_one("#chapters", DataTable)
        chapters.add_columns("Read", "Chapter", "Exercises")
        self.query_one("#bullets", DataTable).add_column("Bullet")
        self.refresh_desk()
        self.query_one("#items").focus()
        self.set_interval(15, self.check_date)
        self.apply_width(self.size.width)
        self.call_after_refresh(self.refresh_desk)

    def on_resize(self, event):
        if self.is_mounted:
            self.apply_width(event.size.width)
            self.call_after_refresh(self.refresh_desk)

    def apply_width(self, width):
        show_today = self.today_override if self.today_override is not None else width >= 110
        self.query_one("#journal").display = show_today
        self.set_class(width < 110, "compact")
        self.query_one("#library").display = not (width < 75 and show_today)
        self.query_one("#show-today", Button).label = "Today" if width < 110 else "Hide today" if show_today else "Show today"
        self.query_one("#show-today", Button).variant = "primary" if show_today and width < 110 else "default"

    def check_date(self):
        today = date.today()
        if today != self.last_today:
            if self.journal_day == self.last_today:
                self.journal_day = today
            self.last_today = today
            self.refresh_desk()

    @staticmethod
    def row_id(table):
        if table.row_count:
            return int(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        return None

    def fill(self, selector, rows, selected=None):
        table = self.query_one(selector, DataTable)
        selected = selected if selected is not None else self.row_id(table)
        with self.prevent(DataTable.RowHighlighted):
            wrapped = selector in {"#items", "#bullets", "#syllabus", "#tasks"}
            table.clear(columns=wrapped)
            if wrapped:
                table.wrapped_rows = rows
                table.filled_width = table.size.width
                # Reserve the scrollbar even before it appears, to avoid a
                # width/height feedback loop when long rows start wrapping.
                available = max(1, table.size.width - table.styles.scrollbar_size_vertical)
                padding = 2 * table.cell_padding
                if selector in {"#syllabus", "#tasks"}:
                    kind_width = min(8 if selector == "#syllabus" else 18, max(1, available - 5))
                    table.add_column("Activity", width=max(1, available - kind_width - 2 * padding))
                    table.add_column("Type", width=kind_width)
                else:
                    table.add_column("Item", width=max(1, available - padding))
            for item_id, cells in rows:
                table.add_row(*cells, key=str(item_id), height=None if wrapped else 1)
            ids = [item_id for item_id, _ in rows]
            if ids:
                table.move_cursor(row=ids.index(selected) if selected in ids else 0)
        self.refresh_rename_controls()
        return self.row_id(table)

    def detail_selection(self):
        return {"paths": "syllabus", "books": "chapters", "habits": "items", "skills": "items", "projects": "tasks", "ideas": "items"}[self.mode]

    def refresh_rename_controls(self):
        names = {"paths": "path", "books": "book", "habits": "habit", "skills": "skill", "projects": "project", "ideas": "idea"}
        for button_id, selector, name in (
            ("rename-item", "items", names[self.mode]),
            ("rename-detail", self.detail_selection(), {"paths": "activity or module", "books": "chapter", "projects": "step"}.get(self.mode, names[self.mode])),
            ("rename-bullet", "bullets", "journal task or note"),
        ):
            button = self.query_one(f"#{button_id}", Button)
            button.disabled = not self.query_one(f"#{selector}", DataTable).row_count
            button.tooltip = f"Rename the selected {name} · shortcut: r · Ctrl+Z undoes changes"

    def status(self, message):
        self.query_one("#status", Static).update(Text(message, style="#b7c8d9"))

    def refresh_desk(self):
        today = date.today()
        self.query_one("#date", Static).update(today.strftime("%a %d %b %Y") + ("  /  Demo" if self.demo else ""))
        books = self.mode == "books"
        for mode, button in (("paths", "show-paths"), ("books", "show-books"), ("habits", "show-habits"),
                             ("skills", "show-skills"), ("projects", "show-projects"), ("ideas", "show-ideas")):
            self.query_one(f"#{button}", Button).variant = "primary" if self.mode == mode else "default"
        self.query_one("#import-syllabus").display = self.mode == "paths"
        if self.mode in {"paths", "skills", "projects", "ideas"}:
            {"projects": self.refresh_project_list, "ideas": self.refresh_idea_list}.get(self.mode, self.refresh_learning_list)()
            self.refresh_detail()
            self.refresh_journal()
            return
        self.query_one("#library-title", Label).update(self.sidebar_title("Books" if books else "Habits"))
        self.query_one("#add-item", Button).label = "+ Book" if books else "+ Habit"
        if books:
            items = self.store.sidebar_items("books")
            progress = {b["id"]: Text(self.pin_title(b) + "\n") for b in items}
            for unit in self.store.rows("SELECT book_id,reading FROM chapters ORDER BY book_id,position,id"):
                if unit["book_id"] not in progress:
                    continue
                state = unit["reading"]
                progress[unit["book_id"]].append(
                    ("□", "◧", "■")[state] + " ",
                    style=("#667d94", "#e5bc72", "#74c5b2")[state],
                )
            self.book_id = self.fill("#items", [(b["id"], [progress[b["id"]]]) for b in items], self.book_id)
        else:
            items = self.store.sidebar_items("habits")
            monday = self.journal_day - timedelta(days=self.journal_day.weekday())
            rows = []
            for habit in items:
                depth = habit["sidebar_depth"]
                progress = Text(("  " * (depth - 1) + "↳ " if depth else "") + self.pin_title(habit) + "\n")
                counts = self.store.habit_counts(habit["id"], planned=False)
                plans = self.store.habit_counts(habit["id"], planned=True)
                for offset in range(7):
                    day = monday + timedelta(days=offset)
                    amount = counts.get(day.isoformat(), 0)
                    if plans.get(day.isoformat(), 0):
                        progress.append("◇ ", style="#8fa5bb")
                        continue
                    state = 2 if amount >= (habit["daily_goal"] if habit["goal_period"] == "day" else 1) else 1 if amount else 0
                    progress.append(
                        ("□", "◧", "■")[state] + " ",
                        style="#8fa5bb" if day > today and amount else "#30455b" if day > today else ("#667d94", "#e5bc72", "#74c5b2")[state],
                    )
                rows.append((habit["id"], [progress]))
            self.habit_id = self.fill("#items", rows, self.habit_id)
        self.query_one("#library-empty", Static).update(self.empty_sidebar("Add your first book below." if books else "Add a habit to begin."))
        self.query_one("#library-empty").display = not items
        self.query_one("#items").display = bool(items)
        self.overview(f"{len(items)} {'books' if books else 'habits'}")
        self.refresh_detail()
        self.refresh_journal()

    def refresh_detail(self):
        books = self.mode == "books"
        learning = self.mode in {"paths", "skills"}
        projects = self.mode == "projects"
        ideas = self.mode == "ideas"
        self.query_one("#idea-detail").display = ideas
        self.query_one("#idea-actions").display = ideas
        self.query_one("#tasks").display = projects
        self.query_one("#project-info").display = projects
        self.query_one("#project-actions").display = projects
        self.query_one("#syllabus").display = self.mode == "paths"
        self.query_one("#skills-detail").display = self.mode == "skills"
        self.query_one("#learning-info").display = self.mode == "paths"
        self.query_one("#learning-actions").display = self.mode == "paths"
        self.query_one("#detail-hint").display = not (learning or projects or ideas)
        self.query_one("#chapters").display = books
        self.query_one("#chapter-actions").display = books
        self.query_one("#habit-detail").display = self.mode == "habits"
        self.query_one("#progress").display = books
        self.query_one("#detail-empty").display = False
        if learning:
            self.refresh_learning_detail()
            return
        if projects:
            self.refresh_project_detail()
            return
        if ideas:
            self.refresh_idea_detail()
            return
        if books:
            matches = self.store.rows("SELECT * FROM books WHERE id=?", (self.book_id,))
            if not matches:
                self.query_one("#detail-title", Label).update("Your reading desk")
                self.query_one("#progress", Static).update("Add a book, then list its chapters.")
                self.fill("#chapters", [])
                self.query_one("#chapter-actions").display = False
                return
            book = matches[0]
            chapters = self.store.rows("SELECT * FROM chapters WHERE book_id=? ORDER BY position,id", (self.book_id,))
            done = sum(c["reading"] == 2 for c in chapters)
            progress = Text()
            for c in chapters:
                progress.append(("□", "◧", "■")[c["reading"]] + " ", ("#667d94", "#e5bc72", "#74c5b2")[c["reading"]])
            progress.append(f"\n{done}/{len(chapters)} chapters read", style="#b7c8d9")
            self.query_one("#detail-title", Label).update(Text(book["title"]))
            self.query_one("#progress", Static).update(progress)
            self.fill("#chapters", [(c["id"], [Text(("□", "◧", "■")[c["reading"]], style=("#667d94", "#e5bc72", "#74c5b2")[c["reading"]]), Text(c["title"]), ("✓" if c["exercises"] else "□") if book["textbook"] else "—"]) for c in chapters])
            self.query_one("#detail-empty").display = not chapters
            self.query_one("#detail-empty", Static).update("Add chapters below, or paste a chapter list when creating a book.")
            self.query_one("#detail-hint", Static).update("Enter / Space: reading status   e: exercises   p: plan today" if book["textbook"] else "Enter / Space: reading status   p: plan today")
        else:
            self.query_one("#detail-hint", Static).update("+ / −: log on selected date   Ctrl+Left/Right: change date")
            matches = self.store.rows("SELECT * FROM habits WHERE id=?", (self.habit_id,))
            self.query_one("#habit-detail").display = bool(matches)
            self.query_one("#detail-title", Label).update(Text(matches[0]["title"]) if matches else "Your daily rhythms")
            if matches:
                self.render_habit(matches[0])

    def render_habit(self, habit):
        today = date.today()
        selected = self.journal_day
        counts = self.store.habit_counts(habit["id"], planned=False)
        plans = self.store.habit_counts(habit["id"], planned=True)
        direct = self.store.rows("SELECT amount FROM checkins WHERE habit_id=? AND day=?", (habit["id"], selected.isoformat()))
        own = direct[0]["amount"] if direct else 0
        monday = selected - timedelta(days=selected.weekday())
        days = [monday + timedelta(days=n) for n in range(7)]
        actual = [d for d in days if d <= today]

        if habit["goal_period"] == "week":
            weekly = sum(counts.get(d.isoformat(), 0) for d in actual)
            planned = sum(plans.get(d.isoformat(), 0) for d in days)
            goal = f'{habit["daily_goal"]} {habit["unit"]} / week'
            week_line = f'Week of {monday:%d %b}: {weekly} / {habit["daily_goal"]} {habit["unit"]}; {planned} planned'
            day_line = f'{counts.get(selected.isoformat(), 0)} recorded + {plans.get(selected.isoformat(), 0)} planned {habit["unit"]}'
        else:
            weekly = sum(counts.get(d.isoformat(), 0) >= habit["daily_goal"] for d in actual)
            planned = sum(plans.get(d.isoformat(), 0) >= habit["daily_goal"] for d in days)
            goal = f'{habit["daily_goal"]} {habit["unit"]} / day, {habit["weekly_goal"]} days / week'
            week_line = f'Week of {monday:%d %b}: {weekly} / {habit["weekly_goal"]} days; {planned} planned'
            day_line = f'{counts.get(selected.isoformat(), 0)} / {habit["daily_goal"]} {habit["unit"]}; {plans.get(selected.isoformat(), 0)} planned'
        label = "Planned" if selected > today else "Recorded"
        self.query_one("#habit-summary", Static).update(Text(
            f'{selected:%a %d %b %Y} · {label}\n{day_line} (direct: {own})\n'
            f'Goal: {goal}\n{week_line}\n\n12 weeks through selected week', style="#b7c8d9"))
        start = monday - timedelta(weeks=11)
        grid = Text()
        grid.append("    ")
        for week in range(12):
            d = start + timedelta(weeks=week)
            grid.append(d.strftime("%b")[:2] if week == 0 or d.month != (d-timedelta(weeks=1)).month else "  ")
        grid.append("\n")
        for weekday, label in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
            grid.append(label + " ", style="#8fa5bb")
            for week in range(12):
                day = start + timedelta(weeks=week, days=weekday)
                amount = counts.get(day.isoformat(), 0)
                if plans.get(day.isoformat(), 0) or day > today:
                    grid.append("◇ " if plans.get(day.isoformat(), 0) else "  ", style="#8fa5bb")
                else:
                    level = min(3, max(1, int(amount / (habit["daily_goal"] if habit["goal_period"] == "day" else 1) * 3))) if amount else 0
                    grid.append("■ ", style=("#30455b", "#376d70", "#52a394", "#9ae2c9")[level])
            grid.append("\n")
        self.query_one("#heatmap", Static).update(grid)
        self.query_one("#habit-legend", Static).update("■ none / partial / goal met    ◇ planned\nWeekly goals: shading shows days with activity.\nTotals include children; edits change direct entries.\nSet amount on or after the date confirms a plan.")

    def refresh_journal(self):
        day = self.journal_day.isoformat()
        today = self.journal_day == date.today()
        self.query_one("#journal-title", Label).update("Today" if today else "Plan ahead" if self.journal_day > date.today() else "Journal history")
        bullets = self.store.rows("SELECT * FROM bullets WHERE day=? ORDER BY id", (day,))
        done = sum(bool(b["done"]) for b in bullets if not b["note"])
        tasks = sum(not b["note"] and not b["migrated"] for b in bullets)
        self.query_one("#journal-summary", Static).update(f'{self.journal_day:%a %d %b}\n{done}/{tasks} tasks completed')
        rows = []
        for bullet in bullets:
            marker = "–" if bullet["note"] else "›" if bullet["migrated"] else "×" if bullet["done"] else "•"
            text = Text(f'{marker} {bullet["text"]}', style="#8296aa" if bullet["done"] or bullet["migrated"] else "#dbe6ef")
            if bullet["chapter_id"] or bullet["habit_id"] or bullet["activity_id"] or bullet["project_task_id"]:
                text.append(" ↗", style="#74c5b2")
            rows.append((bullet["id"], [text]))
        self.fill("#bullets", rows)
        self.query_one("#bullets").display = bool(bullets)
        self.query_one("#journal-empty").display = not bullets
        self.query_one("#journal-empty", Static).update("A fresh page.\nJot a task or a thought below.")

    @on(DataTable.RowHighlighted, "#syllabus")
    def highlighted_activity(self):
        if self.mode == "paths":
            self.render_activity_info()

    @on(DataTable.RowHighlighted, "#items")
    def selected_item(self, event):
        if event.row_key.value is None:
            return
        if self.mode == "books":
            self.book_id = int(event.row_key.value)
        elif self.mode == "habits":
            self.habit_id = int(event.row_key.value)
        elif self.mode == "paths":
            self.path_id = int(event.row_key.value)
        elif self.mode == "projects":
            self.project_id = int(event.row_key.value)
        elif self.mode == "ideas":
            self.idea_id = int(event.row_key.value)
        else:
            self.skill_id = int(event.row_key.value)
        self.refresh_rename_controls()
        self.refresh_detail()

    @on(DataTable.RowSelected)
    def selected_row(self, event):
        if event.data_table.id == "items":
            if self.mode == "books":
                self.query_one("#chapters").focus()
            elif self.mode == "paths":
                self.query_one("#syllabus").focus()
            elif self.mode == "projects":
                self.query_one("#tasks").focus()
            elif self.mode == "ideas":
                self.edit_idea()
            elif self.mode == "skills":
                self.edit_skill()
        elif event.data_table.id == "syllabus":
            self.activate_activity()
        elif event.data_table.id == "tasks":
            self.activate_task()
        elif event.data_table.id == "chapters":
            self.advance_chapter()
        elif event.data_table.id == "bullets":
            self.complete_bullet()

    @on(Button.Pressed)
    def button(self, event):
        actions = {"show-books": self.action_books, "show-habits": self.action_habits,
                   "show-paths": self.action_paths, "show-skills": self.action_skills,
                   "show-projects": self.action_projects, "add-task": self.add_task,
                   "add-subtask": lambda: self.add_task(child=True), "next-step": self.next_step,
                   "plan-task": self.plan_task, "edit-task": self.edit_task,
                   "show-ideas": self.action_ideas, "edit-idea": self.edit_idea,
                   "idea-project": self.take_up_idea, "idea-step": lambda: self.take_up_idea(as_step=True),
                   "import-syllabus": self.action_import, "add-activity": self.add_activity,
                   "continue-path": self.action_continue, "view-visual": self.action_visual,
                   "edit-skill": self.edit_skill,
                   "sidebar-options": self.sidebar_options,
                   "show-today": self.action_today, "add-item": self.add_item,
                   "add-chapter": self.add_chapter, "plan-chapter": self.action_plan,
                   "jot": self.action_jot, "prev-day": self.action_previous_day,
                   "next-day": self.action_next_day, "current-day": self.current_day,
                   "add-unit": self.action_increment, "subtract-unit": self.action_decrement,
                   "log-amount": self.log_amount, "set-amount": self.set_amount,
                   "edit-habit": lambda: self.habit_form(edit=True),
                   "habit-prev": self.action_previous_day, "habit-next": self.action_next_day,
                   "habit-today": self.current_day, "habit-date": self.choose_date}
        actions.update({"rename-item": lambda: self.action_rename("items"),
                        "rename-detail": lambda: self.action_rename(self.detail_selection()),
                        "rename-bullet": lambda: self.action_rename("bullets")})
        if action := actions.get(event.button.id):
            action()

    def sidebar_options(self):
        table = self.mode
        selected = self.row_id(self.query_one("#items", DataTable))
        items = self.store.sidebar_items(table)
        item = next((row for row in items if row["id"] == selected), None)
        siblings = [row["id"] for row in items if table != "habits" or item and row["sidebar_parent"] == item["sidebar_parent"]]
        index = siblings.index(selected) if selected in siblings else -1
        def apply(result):
            if result is None:
                return
            action, value = result
            if action == "sort":
                self.store.set_sidebar_sort(table, value)
                self.refresh_desk()
            elif action == "move":
                self.move_sidebar(value)
            elif action == "pin":
                self.action_pin()
            elif action == "shelve":
                self.action_shelve()
            elif action == "manage":
                self.manage_shelves()
            elif action == "previews":
                self.store.set_previews(table, value)
                self.refresh_desk()
            else:
                self.store.set_view(**{"focus" if action == "focus" else "shelf": value})
                self.refresh_desk()
        self.push_screen(SidebarOptions(
            table, self.store.sidebar_sorts(table), self.store.sidebar_sort(table),
            item["title"] if item else None, index > 0, 0 <= index < len(siblings) - 1,
            pinned=bool(item and item["pinned"]), view=self.store.view(), shelves=self.store.shelves(),
            previews=self.store.previews(table) if table in self.store.PREVIEWS else None), apply)

    def move_sidebar(self, direction):
        item_id = self.row_id(self.query_one("#items", DataTable))
        if item_id is None:
            return
        if self.store.move_sidebar_item(self.mode, item_id, direction):
            setattr(self, {"books": "book_id", "habits": "habit_id", "paths": "path_id", "skills": "skill_id",
                           "projects": "project_id", "ideas": "idea_id"}[self.mode], item_id)
            self.refresh_desk()
            self.query_one("#items").focus()
            self.status("Order saved. Habit groups move together; children move among siblings. Ctrl+Z undoes this change.")
        else:
            self.status("Already at the edge of this group." if self.mode == "habits" else "Already at the edge of this list.")

    def action_move_up(self):
        if getattr(self.focused, "id", None) == "tasks":
            self.move_task(-1)
        elif self.focused is not None and self.query_one("#library") in self.focused.ancestors:
            self.move_sidebar(-1)

    def action_move_down(self):
        if getattr(self.focused, "id", None) == "tasks":
            self.move_task(1)
        elif self.focused is not None and self.query_one("#library") in self.focused.ancestors:
            self.move_sidebar(1)

    def action_indent(self):
        if getattr(self.focused, "id", None) == "tasks":
            self.indent_task()

    def action_outdent(self):
        if getattr(self.focused, "id", None) == "tasks":
            self.indent_task(outdent=True)

    def action_child(self):
        if self.mode == "projects":
            self.add_task(child=True)
        else:
            super().action_child()

    def action_continue(self):
        if self.mode == "projects":
            self.next_step()
        else:
            super().action_continue()

    def action_inspect(self):
        if self.mode == "projects":
            self.edit_task()
        elif self.mode == "ideas":
            self.edit_idea()
        else:
            super().action_inspect()

    def action_books(self):
        self.mode = "books"
        self.refresh_desk()
        self.query_one("#items").focus()

    def action_habits(self):
        self.mode = "habits"
        self.refresh_desk()
        self.query_one("#items").focus()

    def action_today(self):
        self.today_override = not self.query_one("#journal").display
        self.apply_width(self.size.width)
        if self.today_override:
            self.query_one("#bullets" if self.query_one("#bullets").display else "#jot").focus()

    def action_help(self):
        self.push_screen(Help())

    def action_add(self):
        focused = getattr(self.focused, "id", None)
        if focused in {"bullets", "jot"}:
            self.action_jot()
        elif focused == "chapters":
            self.add_chapter()
        elif focused == "syllabus":
            self.add_activity()
        elif focused == "tasks":
            self.add_task()
        else:
            self.add_item()

    def add_item(self):
        if self.mode in {"paths", "skills"}:
            self.add_learning_item()
            return
        if self.mode == "projects":
            self.add_project()
            return
        if self.mode == "ideas":
            self.add_idea()
            return
        if self.mode == "books":
            def save(values):
                if values:
                    titles = [line.strip() for line in values["chapters"].splitlines() if line.strip()]
                    self.book_id = self.store.add_book(values["title"], titles, values["textbook"])
                    self.store.adopt_view("books", self.book_id)
                    self.refresh_desk()
            self.push_screen(Form("Add a book", [("title", "Book title", "", False), ("chapters", "Chapters — one per line (optional)", "", True)], textbook=True), save)
        else:
            self.habit_form()

    def habit_form(self, edit=False):
        habit_id = self.habit_id if edit else None
        if edit and habit_id is None:
            return
        habit = self.store.rows("SELECT * FROM habits WHERE id=?", (habit_id,))[0] if edit else {
            "title": "", "unit": "sessions", "daily_goal": 1, "weekly_goal": 7,
            "goal_period": "day", "parent_id": None}
        def validate(values):
            self.store.validate_habit(values["unit"] or "sessions", values["daily"], values["weekly"],
                                      values["goal-period"], values["parent"] or None, habit_id)
        def save(values):
            if values:
                args = (values["title"], values["unit"] or "sessions", values["daily"], values["weekly"],
                        values["goal-period"], values["parent"] or None)
                if edit:
                    self.store.edit_habit(habit_id, *args)
                else:
                    self.habit_id = self.store.add_habit(*args)
                    self.store.adopt_view("habits", self.habit_id)
                self.refresh_desk()
        parents = [("No parent", 0)] + [(h["title"], h["id"]) for h in self.store.rows("SELECT * FROM habits ORDER BY id") if h["id"] != habit_id]
        form = HabitForm("Edit habit" if edit else "Add a habit", [
            ("title", "Habit", habit["title"], False), ("unit", "Unit (same as parent, if grouped)", habit["unit"], False),
            ("daily", "Goal amount per chosen period", str(habit["daily_goal"]), False),
            ("weekly", "Days per week (daily goals only)", str(habit["weekly_goal"]), False)],
            choices={"goal-period": ("How do you want to set your goal?", [("Amount on each active day", "day"), ("Total per week — any days", "week")], habit["goal_period"]),
                     "parent": ("Also counts toward (optional)", parents, habit["parent_id"] or 0)}, validator=validate)
        form.add_class("habit-form")
        self.push_screen(form, save)

    def add_chapter(self):
        if self.mode != "books" or self.book_id is None:
            return
        book_id = self.book_id
        def save(values):
            if values:
                self.store.add_chapter(book_id, values["title"])
                self.refresh_desk()
        self.push_screen(Form("Add a chapter", [("title", "Chapter title", "", False)]), save)

    def action_jot(self):
        day = self.journal_day.isoformat()
        def save(values):
            if values:
                self.store.add_bullet(day, values["title"])
                self.refresh_journal()
        self.push_screen(Form(f'Jot something · {self.journal_day:%d %b}', [("title", "Task, or start with '- ' for a note", "", False)]), save)

    def advance_chapter(self, exercises=False):
        if self.mode != "books":
            return
        chapter_id = self.row_id(self.query_one("#chapters", DataTable))
        if chapter_id:
            book = self.store.rows("SELECT textbook FROM books WHERE id=?", (self.book_id,))[0]
            if exercises and not book["textbook"]:
                return
            self.store.cycle_chapter(chapter_id, exercises)
            self.refresh_desk()

    def complete_bullet(self):
        bullet_id = self.row_id(self.query_one("#bullets", DataTable))
        if bullet_id:
            try:
                self.store.toggle_bullet(bullet_id)
            except ValueError as exc:
                self.notify(str(exc), severity="warning")
            self.refresh_desk()

    def action_advance(self):
        focused = getattr(self.focused, "id", None)
        if focused == "chapters":
            self.advance_chapter()
        elif focused == "bullets":
            self.complete_bullet()
        elif focused == "items" and self.mode == "habits":
            self.action_increment()
        elif focused == "syllabus":
            self.advance_activity()
        elif focused == "tasks":
            self.advance_task()
        elif focused == "items" and self.mode == "skills":
            self.edit_skill()

    def action_exercises(self):
        if getattr(self.focused, "id", None) == "chapters":
            self.advance_chapter(True)

    def action_plan(self):
        if self.mode == "paths":
            self.plan_activity()
            return
        if self.mode == "projects":
            self.plan_task()
            return
        if self.mode != "books":
            return
        chapter_id = self.row_id(self.query_one("#chapters", DataTable))
        if not chapter_id:
            return
        chapter = self.store.rows("SELECT title FROM chapters WHERE id=?", (chapter_id,))[0]
        def save(values):
            if values:
                self.store.add_bullet(date.today().isoformat(), values["title"], chapter_id, values["habit_id"])
                self.journal_day = date.today()
                self.today_override = True
                self.apply_width(self.size.width)
                self.refresh_journal()
                self.status("Planned for today. Complete the bullet to update its linked progress.")
        self.push_screen(Form("Plan a chapter for today", [("title", "Task", f'Read: {chapter["title"]}', False)], habits=self.store.rows("SELECT * FROM habits ORDER BY id")), save)

    def increment(self, amount):
        if self.mode == "habits" and self.habit_id is not None:
            self.store.checkin(self.habit_id, self.journal_day.isoformat(), amount)
            self.refresh_desk()

    def action_increment(self):
        self.increment(1)

    def action_decrement(self):
        self.increment(-1)

    def log_amount(self):
        if self.habit_id is None:
            return
        def save(values):
            if values:
                self.increment(values["daily"])
        self.push_screen(Form(f"Add amount · {self.journal_day:%d %b %Y}", [("daily", "Units to add", "1", False)]), save)

    def set_amount(self):
        if self.habit_id is None:
            return
        habit_id, day = self.habit_id, self.journal_day.isoformat()
        rows = self.store.rows("SELECT amount FROM checkins WHERE habit_id=? AND day=?", (habit_id, day))
        def validate(values):
            try:
                amount = int(values["amount"])
                if amount < 0:
                    raise ValueError
            except ValueError:
                raise ValueError("Enter a nonnegative whole number; 0 clears the direct entry.")
            values["amount"] = amount
        def save(values):
            if values:
                self.store.set_checkin(habit_id, day, values["amount"])
                self.refresh_desk()
        self.push_screen(Form(f"Set direct amount · {day}", [("amount", "Total units (child entries are separate)", str(rows[0]["amount"] if rows else 0), False)], validator=validate), save)

    def choose_date(self):
        def validate(values):
            try:
                values["day"] = date.fromisoformat(values["day"])
            except ValueError:
                raise ValueError("Enter a date as YYYY-MM-DD.")
        def save(values):
            if values:
                self.journal_day = values["day"]
                self.refresh_desk()
        self.push_screen(Form("Choose a date", [("day", "Date (YYYY-MM-DD)", self.journal_day.isoformat(), False)], validator=validate), save)

    def selected_record(self, selector=None):
        focused = selector or getattr(self.focused, "id", None)
        table = {"items": self.mode, "chapters": "chapters", "bullets": "bullets", "syllabus": "activities",
                 "tasks": "project_tasks"}.get(focused)
        if table:
            return table, self.row_id(self.query_one(f"#{focused}", DataTable))
        return None, None

    def action_rename(self, selector=None):
        if selector is None and self.focused is not None:
            # Buttons and other pane controls take focus when clicked. Resolve
            # their pane rather than silently losing the selected record.
            for pane, target in (("library", "items"), ("contents", self.detail_selection()), ("journal", "bullets")):
                if self.query_one(f"#{pane}") in self.focused.ancestors:
                    selector = target
                    break
        table, item_id = self.selected_record(selector)
        if not item_id:
            self.status("Select an item in a pane to rename it.")
            return
        row = self.store.rows(f"SELECT * FROM {table} WHERE id=?", (item_id,))[0]
        name = {"paths": "path", "activities": "activity", "books": "book", "chapters": "chapter",
                "habits": "habit", "skills": "skill", "bullets": "task or note", "projects": "project",
                "project_tasks": "step", "ideas": "idea"}[table]
        def save(values):
            if values:
                self.store.rename(table, item_id, values["title"])
                self.refresh_desk()
                self.status(f"Renamed {name}. Ctrl+Z undoes this change.")
        self.push_screen(Form(f"Rename {name}", [("title", "New name" if table != "bullets" else "Task or note text",
                                                 row.get("title", row.get("text", "")), False)], select_title=True), save)

    def action_delete(self):
        table, item_id = self.selected_record()
        if item_id:
            if table == "activities":
                self.store.archive_activity(item_id)
            else:
                self.store.delete(table, item_id)
            self.refresh_desk()
            self.status("Deleted. Ctrl+Z restores the item and its linked records.")

    def action_undo(self):
        changed = self.store.undo()
        self.refresh_desk()
        self.status("Undone." if changed else "Nothing to undo in this session.")

    def action_previous_day(self):
        self.journal_day -= timedelta(days=1)
        self.refresh_desk()

    def action_next_day(self):
        self.journal_day += timedelta(days=1)
        self.refresh_desk()

    def current_day(self):
        self.journal_day = date.today()
        self.refresh_desk()

    def action_migrate(self):
        if getattr(self.focused, "id", None) != "bullets":
            return
        bullet_id = self.row_id(self.query_one("#bullets", DataTable))
        if bullet_id and self.store.migrate(bullet_id, date.today().isoformat()):
            self.refresh_journal()
            self.status("Carried forward to today. The original stays in history.")
