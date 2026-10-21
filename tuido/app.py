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

    def __init__(self, title, fields, *, textbook=False, habits=None, choices=None, validator=None):
        super().__init__()
        self.heading, self.fields = title, fields
        self.textbook, self.habits = textbook, habits
        self.choices = choices or {}
        self.validator = validator

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="dialog"):
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
        for name, low, high in (("daily", 1, 1000000), ("weekly", 1, 7)):
            if name in values:
                try:
                    values[name] = int(values[name])
                    if not low <= values[name] <= high:
                        raise ValueError
                except ValueError:
                    self.query_one("#form-error", Static).update(f"{name.capitalize()} goal must be a whole number from {low} to {high}.")
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

    @on(Input.Submitted)
    def submitted(self):
        self.save()


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
                "r                 Rename the selected item\n"
                "Delete            Delete selected item (Ctrl+Z to undo)\n"
                "+ / -             Add / subtract one habit unit today\n"
                "Ctrl+J            Jot a task (prefix '- ' for a note)\n"
                "Ctrl+T            Show / hide the daily pane\n"
                "F1 / F2 / F3 / F4 Paths / Library / Habits / Skills\n"
                "Ctrl+O            Preview and import a syllabus JSON file\n"
                "c                 Add a child inside the selected module\n"
                "n                 Continue the next ready required activity\n"
                "i / v             Inspect notes / open syllabus diagrams\n"
                "Ctrl+Left/Right   Browse journal dates\n"
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
                "Habit shading shows progress toward a daily goal. Weekly targets\n"
                "count days that met that goal. Future dates are left blank."
            )
            yield Button("Back to the desk", id="close-help")

    @on(Button.Pressed)
    def close_help(self):
        self.dismiss()


class Tuido(LearningUI, App):
    TITLE = "Tuido"
    CSS_PATH = "desk.tcss"
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("f1", "paths", "Paths"),
        Binding("f2", "books", "Library"),
        Binding("f3", "habits", "Habits"),
        Binding("f4", "skills", "Skills"),
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
        Binding("r", "rename", "Rename", show=False),
        Binding("delete", "delete", "Delete", show=False),
        Binding("plus,equals", "increment", "+ Unit", show=False),
        Binding("minus", "decrement", "− Unit", show=False),
        Binding("ctrl+z", "undo", "Undo"),
        Binding("ctrl+left", "previous_day", "Previous day", show=False),
        Binding("ctrl+right", "next_day", "Next day", show=False),
        Binding("ctrl+y", "migrate", "Carry forward", show=False),
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
        self.collapsed = set()
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
            yield Static("", id="overview")
            yield Button("Today", id="show-today")
        with Horizontal(id="desk"):
            with Vertical(id="library", classes="panel"):
                yield Label("Books", id="library-title", classes="heading")
                yield WrappingTable(id="items", cursor_type="row", show_header=False, show_row_labels=False)
                yield Static("", id="library-empty", classes="empty")
                yield Button("+ Book", id="add-item")
                yield Button("Import syllabus", id="import-syllabus")
            with Vertical(id="contents", classes="panel"):
                yield Label("Choose a book", id="detail-title", classes="heading")
                yield Static("", id="progress")
                yield DataTable(id="chapters", cursor_type="row", show_row_labels=False)
                yield WrappingTable(id="syllabus", cursor_type="row", show_header=False, show_row_labels=False)
                with VerticalScroll(id="skills-detail"):
                    yield Static("", id="skill-description")
                    yield Button("Record progress & evidence", id="edit-skill")
                with VerticalScroll(id="habit-detail"):
                    yield Static("", id="habit-summary")
                    yield Static("", id="heatmap")
                    yield Static("", id="habit-legend")
                    with Horizontal(classes="buttons"):
                        yield Button("− 1", id="subtract-unit")
                        yield Button("+ 1 unit", id="add-unit", variant="primary")
                        yield Button("Log amount", id="log-amount")
                yield Static("", id="detail-empty", classes="empty")
                yield Static("", id="detail-hint", classes="hint")
                yield Static("", id="learning-info", classes="hint")
                with Horizontal(id="learning-actions", classes="buttons"):
                    yield Button("+ Activity", id="add-activity")
                    yield Button("Continue", id="continue-path")
                    yield Button("Visuals", id="view-visual")
                with Horizontal(id="chapter-actions", classes="buttons"):
                    yield Button("+ Chapter", id="add-chapter")
                    yield Button("Plan today", id="plan-chapter")
            with Vertical(id="journal", classes="panel"):
                yield Label("Today", id="journal-title", classes="heading")
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
        self.query_one("#show-today", Button).label = "Hide today" if show_today else "Show today"

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
            wrapped = selector in {"#items", "#bullets", "#syllabus"}
            table.clear(columns=wrapped)
            if wrapped:
                table.wrapped_rows = rows
                table.filled_width = table.size.width
                # Reserve the scrollbar even before it appears, to avoid a
                # width/height feedback loop when long rows start wrapping.
                available = max(1, table.size.width - table.styles.scrollbar_size_vertical)
                padding = 2 * table.cell_padding
                if selector == "#syllabus":
                    kind_width = min(8, max(1, available - 5))
                    table.add_column("Activity", width=max(1, available - kind_width - 2 * padding))
                    table.add_column("Type", width=kind_width)
                else:
                    table.add_column("Item", width=max(1, available - padding))
            for item_id, cells in rows:
                table.add_row(*cells, key=str(item_id), height=None if wrapped else 1)
            ids = [item_id for item_id, _ in rows]
            if ids:
                table.move_cursor(row=ids.index(selected) if selected in ids else 0)
        return self.row_id(table)

    def status(self, message):
        self.query_one("#status", Static).update(Text(message, style="#b7c8d9"))

    def refresh_desk(self):
        today = date.today()
        self.query_one("#date", Static).update(today.strftime("%a %d %b %Y") + ("  /  Demo" if self.demo else ""))
        books = self.mode == "books"
        for mode, button in (("paths", "show-paths"), ("books", "show-books"), ("habits", "show-habits"), ("skills", "show-skills")):
            self.query_one(f"#{button}", Button).variant = "primary" if self.mode == mode else "default"
        self.query_one("#import-syllabus").display = self.mode == "paths"
        if self.mode in {"paths", "skills"}:
            self.refresh_learning_list()
            self.refresh_detail()
            self.refresh_journal()
            return
        self.query_one("#show-books", Button).variant = "primary" if books else "default"
        self.query_one("#show-habits", Button).variant = "default" if books else "primary"
        self.query_one("#library-title", Label).update("Books" if books else "Habits")
        self.query_one("#add-item", Button).label = "+ Book" if books else "+ Habit"
        if books:
            items = self.store.rows("SELECT * FROM books ORDER BY id")
            progress = {b["id"]: Text(b["title"] + "\n") for b in items}
            for unit in self.store.rows("SELECT book_id,reading FROM chapters ORDER BY book_id,position,id"):
                state = unit["reading"]
                progress[unit["book_id"]].append(
                    ("□", "◧", "■")[state] + " ",
                    style=("#667d94", "#e5bc72", "#74c5b2")[state],
                )
            self.book_id = self.fill("#items", [(b["id"], [progress[b["id"]]]) for b in items], self.book_id)
        else:
            items = self.store.rows("SELECT * FROM habits ORDER BY id")
            monday = today - timedelta(days=today.weekday())
            sunday = monday + timedelta(days=6)
            counts = {(r["habit_id"], r["day"]): r["amount"] for r in self.store.rows(
                "SELECT habit_id,day,amount FROM checkins WHERE day BETWEEN ? AND ?",
                (monday.isoformat(), sunday.isoformat()),
            )}
            rows = []
            for habit in items:
                progress = Text(habit["title"] + "\n")
                for offset in range(7):
                    day = monday + timedelta(days=offset)
                    amount = counts.get((habit["id"], day.isoformat()), 0) if day <= today else 0
                    state = 2 if amount >= habit["daily_goal"] else 1 if amount else 0
                    progress.append(
                        ("□", "◧", "■")[state] + " ",
                        style="#30455b" if day > today else ("#667d94", "#e5bc72", "#74c5b2")[state],
                    )
                rows.append((habit["id"], [progress]))
            self.habit_id = self.fill("#items", rows, self.habit_id)
        self.query_one("#library-empty", Static).update("Add your first book below." if books else "Add a habit to begin.")
        self.query_one("#library-empty").display = not items
        self.query_one("#items").display = bool(items)
        self.query_one("#overview", Static).update(f"{len(items)} {'books' if books else 'habits'}")
        self.refresh_detail()
        self.refresh_journal()

    def refresh_detail(self):
        books = self.mode == "books"
        learning = self.mode in {"paths", "skills"}
        self.query_one("#syllabus").display = self.mode == "paths"
        self.query_one("#skills-detail").display = self.mode == "skills"
        self.query_one("#learning-info").display = self.mode == "paths"
        self.query_one("#learning-actions").display = self.mode == "paths"
        self.query_one("#detail-hint").display = not learning
        self.query_one("#chapters").display = books
        self.query_one("#chapter-actions").display = books
        self.query_one("#habit-detail").display = self.mode == "habits"
        self.query_one("#progress").display = books
        self.query_one("#detail-empty").display = False
        if learning:
            self.refresh_learning_detail()
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
            self.query_one("#detail-hint", Static).update("+ / −: log a unit today   Shading follows your daily goal")
            matches = self.store.rows("SELECT * FROM habits WHERE id=?", (self.habit_id,))
            self.query_one("#habit-detail").display = bool(matches)
            self.query_one("#detail-title", Label).update(Text(matches[0]["title"]) if matches else "Your daily rhythms")
            if matches:
                self.render_habit(matches[0])

    def render_habit(self, habit):
        today = date.today()
        counts = {r["day"]: r["amount"] for r in self.store.rows("SELECT day,amount FROM checkins WHERE habit_id=?", (habit["id"],))}
        monday = today - timedelta(days=today.weekday())
        weekly = sum(counts.get((monday+timedelta(days=n)).isoformat(), 0) >= habit["daily_goal"] for n in range(today.weekday()+1))
        self.query_one("#habit-summary", Static).update(Text(
            f'Today   {counts.get(today.isoformat(),0)} / {habit["daily_goal"]} {habit["unit"]}\n'
            f'This week   {weekly} / {habit["weekly_goal"]} days\n\nLast 12 weeks', style="#b7c8d9"))
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
                if day > today:
                    grid.append("  ")
                else:
                    level = min(3, max(1, int(amount / habit["daily_goal"] * 3))) if amount else 0
                    grid.append("■ ", style=("#30455b", "#376d70", "#52a394", "#9ae2c9")[level])
            grid.append("\n")
        self.query_one("#heatmap", Static).update(grid)
        self.query_one("#habit-legend", Static).update("■ none    ▧ partial    ■ goal met\nEach column is a week; each row is a weekday.")

    def refresh_journal(self):
        day = self.journal_day.isoformat()
        today = self.journal_day == date.today()
        self.query_one("#journal-title", Label).update("Today" if today else "Journal history")
        bullets = self.store.rows("SELECT * FROM bullets WHERE day=? ORDER BY id", (day,))
        done = sum(bool(b["done"]) for b in bullets if not b["note"])
        tasks = sum(not b["note"] and not b["migrated"] for b in bullets)
        self.query_one("#journal-summary", Static).update(f'{self.journal_day:%a %d %b}\n{done}/{tasks} tasks completed')
        rows = []
        for bullet in bullets:
            marker = "–" if bullet["note"] else "›" if bullet["migrated"] else "×" if bullet["done"] else "•"
            text = Text(f'{marker} {bullet["text"]}', style="#8296aa" if bullet["done"] or bullet["migrated"] else "#dbe6ef")
            if bullet["chapter_id"] or bullet["habit_id"] or bullet["activity_id"]:
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
        else:
            self.skill_id = int(event.row_key.value)
        self.refresh_detail()

    @on(DataTable.RowSelected)
    def selected_row(self, event):
        if event.data_table.id == "items":
            if self.mode == "books":
                self.query_one("#chapters").focus()
            elif self.mode == "paths":
                self.query_one("#syllabus").focus()
            elif self.mode == "skills":
                self.edit_skill()
        elif event.data_table.id == "syllabus":
            self.activate_activity()
        elif event.data_table.id == "chapters":
            self.advance_chapter()
        elif event.data_table.id == "bullets":
            self.complete_bullet()

    @on(Button.Pressed)
    def button(self, event):
        actions = {"show-books": self.action_books, "show-habits": self.action_habits,
                   "show-paths": self.action_paths, "show-skills": self.action_skills,
                   "import-syllabus": self.action_import, "add-activity": self.add_activity,
                   "continue-path": self.action_continue, "view-visual": self.action_visual,
                   "edit-skill": self.edit_skill,
                   "show-today": self.action_today, "add-item": self.add_item,
                   "add-chapter": self.add_chapter, "plan-chapter": self.action_plan,
                   "jot": self.action_jot, "prev-day": self.action_previous_day,
                   "next-day": self.action_next_day, "current-day": self.current_day,
                   "add-unit": self.action_increment, "subtract-unit": self.action_decrement,
                   "log-amount": self.log_amount}
        if action := actions.get(event.button.id):
            action()

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
        else:
            self.add_item()

    def add_item(self):
        if self.mode in {"paths", "skills"}:
            self.add_learning_item()
            return
        if self.mode == "books":
            def save(values):
                if values:
                    titles = [line.strip() for line in values["chapters"].splitlines() if line.strip()]
                    self.book_id = self.store.add_book(values["title"], titles, values["textbook"])
                    self.refresh_desk()
            self.push_screen(Form("Add a book", [("title", "Book title", "", False), ("chapters", "Chapters — one per line (optional)", "", True)], textbook=True), save)
        else:
            def save(values):
                if values:
                    self.habit_id = self.store.add_habit(values["title"], values["unit"] or "sessions", values["daily"], values["weekly"])
                    self.refresh_desk()
            self.push_screen(Form("Add a habit", [("title", "Habit", "", False), ("unit", "Unit", "sessions", False), ("daily", "Daily goal (units)", "1", False), ("weekly", "Weekly goal (days meeting daily goal)", "7", False)]), save)

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
        elif focused == "items" and self.mode == "skills":
            self.edit_skill()

    def action_exercises(self):
        if getattr(self.focused, "id", None) == "chapters":
            self.advance_chapter(True)

    def action_plan(self):
        if self.mode == "paths":
            self.plan_activity()
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
            self.store.checkin(self.habit_id, date.today().isoformat(), amount)
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
        self.push_screen(Form("Log an amount today", [("daily", "Units to add", "1", False)]), save)

    def selected_record(self):
        focused = getattr(self.focused, "id", None)
        table = {"items": self.mode, "chapters": "chapters", "bullets": "bullets", "syllabus": "activities"}.get(focused)
        if table:
            return table, self.row_id(self.query_one(f"#{focused}", DataTable))
        return None, None

    def action_rename(self):
        table, item_id = self.selected_record()
        if not item_id:
            return
        row = self.store.rows(f"SELECT * FROM {table} WHERE id=?", (item_id,))[0]
        def save(values):
            if values:
                self.store.rename(table, item_id, values["title"])
                self.refresh_desk()
        self.push_screen(Form("Edit text", [("title", "Text", row.get("title", row.get("text", "")), False)]), save)

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
        self.refresh_journal()

    def action_next_day(self):
        if self.journal_day < date.today():
            self.journal_day += timedelta(days=1)
            self.refresh_journal()

    def current_day(self):
        self.journal_day = date.today()
        self.refresh_journal()

    def action_migrate(self):
        if getattr(self.focused, "id", None) != "bullets":
            return
        bullet_id = self.row_id(self.query_one("#bullets", DataTable))
        if bullet_id and self.store.migrate(bullet_id, date.today().isoformat()):
            self.refresh_journal()
            self.status("Carried forward to today. The original stays in history.")
