from datetime import date, timedelta
import sqlite3

from textual.widgets import DataTable, Input, Select

from tuido.app import Tuido
from tuido.store import Store


def test_subtasks_derive_progress_and_next_step_skips_chores():
    store = Store(":memory:")
    project = store.add_project("Thesis")
    chore = store.add_task(project, "Tidy desk", every_days=7)
    outline = store.add_task(project, "Outline")
    first = store.add_task(project, "Arguments", outline)
    second = store.add_task(project, "Sources", outline)
    assert store.next_task(project) == first
    assert store.cycle_task(first)
    assert store.project_snapshot(project)[2][first] == 1
    store.cycle_task(first)
    nodes, children, states = store.project_snapshot(project)
    assert children[outline] == [first, second]
    assert states[outline] == 1 and states[chore] == 0
    assert store.next_task(project) == second
    store.cycle_task(second)
    store.cycle_task(second)
    assert store.project_snapshot(project)[2][outline] == 2
    assert store.next_task(project) is None
    try:
        store.cycle_task(outline)
        raise AssertionError("parents finish through their subtasks")
    except ValueError:
        pass
    assert store.move_task(second, -1)
    assert store.project_snapshot(project)[1][outline] == [second, first]
    assert not store.move_task(second, -1)


def test_chores_rest_for_their_interval_then_come_back():
    store = Store(":memory:")
    project = store.add_project("Home")
    laundry = store.add_task(project, "Laundry", every_days=7)
    today = date.today()
    assert store.cycle_task(laundry, (today - timedelta(days=3)).isoformat())
    assert store.project_snapshot(project, today)[2][laundry] == 2
    assert not store.cycle_task(laundry, today.isoformat()), "already fresh: no double check"
    assert store.project_snapshot(project, today + timedelta(days=4))[2][laundry] == 0
    store.undo()
    assert store.rows("SELECT last_done FROM project_tasks")[0]["last_done"] is None


def test_today_bullet_completes_linked_step_and_carries_link():
    store = Store(":memory:")
    project = store.add_project("Home")
    step = store.add_task(project, "Fix shelf")
    chore = store.add_task(project, "Laundry", every_days=7)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    old = store.add_bullet(yesterday, "Fix shelf", project_task_id=step)
    assert store.migrate(old, date.today().isoformat())
    carried = store.rows("SELECT * FROM bullets WHERE migrated=0")[0]
    assert carried["project_task_id"] == step
    store.toggle_bullet(carried["id"])
    assert store.rows("SELECT status FROM project_tasks WHERE id=?", (step,))[0]["status"] == 2
    bullet = store.add_bullet(yesterday, "Laundry", project_task_id=chore)
    store.toggle_bullet(bullet)
    assert store.rows("SELECT last_done FROM project_tasks WHERE id=?", (chore,))[0]["last_done"] == yesterday
    store.undo()
    assert store.rows("SELECT last_done FROM project_tasks WHERE id=?", (chore,))[0]["last_done"] is None


def test_focus_and_shelves_filter_every_sidebar_and_survive_undo():
    store = Store(":memory:")
    books = [store.add_book(title, []) for title in ("A", "B", "C", "D")]
    home = store.add_shelf("Home")
    store.toggle_pin("books", books[1])
    store.toggle_pin("books", books[3])
    store.set_shelf("books", books[3], home)
    store.set_view(focus=True)
    assert [b["id"] for b in store.sidebar_items("books")] == [books[1], books[3]]
    # Moving within the filtered list swaps visible neighbours and keeps hidden places.
    assert store.move_sidebar_item("books", books[3], -1)
    assert [b["id"] for b in store.sidebar_items("books", filtered=False)] == [books[0], books[3], books[2], books[1]]
    store.set_view(shelf=home)
    assert [b["id"] for b in store.sidebar_items("books")] == [books[3]]
    store.undo()  # undo the move, not the view
    assert store.view() == {"focus": True, "shelf": home}
    store.set_view(focus=False)
    new = store.add_book("E", [])
    store.adopt_view("books", new)
    assert [b["id"] for b in store.sidebar_items("books")] == [books[3], new]
    store.delete("shelves", home)
    assert store.view()["shelf"] is None
    assert store.rows("SELECT COUNT(*) AS n FROM books WHERE shelf_id IS NOT NULL")[0]["n"] == 0


def test_filtered_habit_child_shows_without_its_parent():
    store = Store(":memory:")
    parent = store.add_habit("Creative")
    child = store.add_habit("Painting", parent_id=parent)
    store.toggle_pin("habits", child)
    store.set_view(focus=True)
    items = store.sidebar_items("habits")
    assert [(h["id"], h["sidebar_depth"]) for h in items] == [(child, 0)]


def test_existing_database_gains_pins_shelves_and_projects(tmp_path):
    path = tmp_path / "before.sqlite3"
    Store(path).close()
    db = sqlite3.connect(path)
    for table in ("shelves", "projects", "project_tasks", "settings"):
        db.execute(f"DROP TABLE {table}")
    db.commit()
    db.close()
    store = Store(path)
    store.add_book("Kept", [])
    project = store.add_project("New")
    store.toggle_pin("projects", project)
    assert '"project_tasks"' in store.export()
    store.close()


async def test_projects_keyboard_flow_and_plan_today():
    store = Store(":memory:")
    app = Tuido(store)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("f5", "a")
        app.screen.query_one("#title", Input).value = "Home"
        await pilot.click("#save")
        await pilot.pause()
        project = store.rows("SELECT id FROM projects")[0]["id"]
        await pilot.press("enter")
        assert app.focused.id == "tasks"
        await pilot.press("a")
        app.screen.query_one("#title", Input).value = "Laundry"
        app.screen.query_one("#repeat", Select).value = 7
        await pilot.click("#save")
        await pilot.pause()
        await pilot.press("a")
        app.screen.query_one("#title", Input).value = "Sort the cupboard"
        await pilot.click("#save")
        await pilot.pause()
        app.query_one("#tasks").focus()
        await pilot.press("down", "c")
        app.screen.query_one("#title", Input).value = "Empty top shelf"
        await pilot.click("#save")
        await pilot.pause()
        tasks = {t["title"]: t for t in store.rows("SELECT * FROM project_tasks")}
        assert tasks["Laundry"]["every_days"] == 7
        assert tasks["Empty top shelf"]["parent_id"] == tasks["Sort the cupboard"]["id"]
        assert app.query_one("#tasks", DataTable).row_count == 3
        await pilot.press("n")
        assert app.row_id(app.query_one("#tasks", DataTable)) == tasks["Empty top shelf"]["id"]
        await pilot.press("p")
        await pilot.click("#save")
        await pilot.pause()
        bullet = store.rows("SELECT * FROM bullets")[0]
        assert bullet["project_task_id"] == tasks["Empty top shelf"]["id"]
        app.query_one("#bullets").focus()
        await pilot.press("enter")
        assert store.project_snapshot(project)[2][tasks["Sort the cupboard"]["id"]] == 2
        app.query_one("#tasks").focus()
        await pilot.press("up", "up", "space")
        assert store.rows("SELECT last_done FROM project_tasks WHERE title='Laundry'")[0]["last_done"] == date.today().isoformat()
        await pilot.press("ctrl+z")
        assert store.rows("SELECT last_done FROM project_tasks WHERE title='Laundry'")[0]["last_done"] is None
    store.close()


async def test_pin_focus_and_shelf_from_the_keyboard():
    store = Store(":memory:")
    for title in ("Laundry list", "Thesis", "Taxes"):
        store.add_project(title)
    app = Tuido(store)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("f5", "down", "asterisk")
        thesis = store.rows("SELECT * FROM projects WHERE title='Thesis'")[0]
        assert thesis["pinned"] == 1
        await pilot.press("f")
        assert app.query_one("#items", DataTable).row_count == 1
        assert "★" in str(app.query_one("#library-title").render()) and "focus" in str(app.query_one("#overview").render())
        await pilot.press("f2")
        assert "Add your first book" in str(app.query_one("#library-empty").render())
        await pilot.press("f5", "s")
        app.screen.query_one("#new-shelf", Input).value = "Uni"
        await pilot.click("#save")
        await pilot.pause()
        shelf = store.rows("SELECT id FROM shelves WHERE title='Uni'")[0]["id"]
        assert store.rows("SELECT shelf_id FROM projects WHERE id=?", (thesis["id"],))[0]["shelf_id"] == shelf
        await pilot.press("f")
        assert app.query_one("#items", DataTable).row_count == 3
        await pilot.click("#sidebar-options")
        await pilot.pause()
        app.screen.query_one("#view-shelf", Select).value = shelf
        await pilot.pause()
        assert store.view()["shelf"] == shelf
        assert app.query_one("#items", DataTable).row_count == 1
        await pilot.press("a")
        app.screen.query_one("#title", Input).value = "Seminar paper"
        await pilot.click("#save")
        await pilot.pause()
        assert app.query_one("#items", DataTable).row_count == 2, "new items join the shown shelf"
    store.close()


async def test_projects_fit_small_terminal():
    store = Store(":memory:")
    store.seed_demo()
    app = Tuido(store)
    async with app.run_test(size=(60, 24)) as pilot:
        await pilot.press("f5")
        await pilot.pause()
        assert app.query_one("#items", DataTable).row_count == 2
        for widget in ("#show-ideas", "#show-today", "#items"):
            assert app.query_one(widget).region.right <= 60
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert app.query_one("#contents").region.right <= 60
    store.close()


def test_indent_and_outdent_steps():
    store = Store(":memory:")
    project = store.add_project("Move flat")
    pack, boxes, label, call = (store.add_task(project, t) for t in ("Pack", "Get boxes", "Label boxes", "Call landlord"))
    assert not store.indent_task(pack), "nothing above the first step"
    assert store.indent_task(boxes) == pack
    assert store.indent_task(label) == pack
    nodes, children, _ = store.project_snapshot(project)
    assert children[None] == [pack, call] and children[pack] == [boxes, label]
    assert store.indent_task(label) == boxes
    assert store.outdent_task(label)
    assert store.project_snapshot(project)[1][pack] == [boxes, label]
    assert store.outdent_task(boxes)
    assert store.project_snapshot(project)[1][None] == [pack, boxes, call]
    assert not store.outdent_task(call)
    store.undo()
    assert store.project_snapshot(project)[1][pack] == [boxes, label]


def test_ideas_are_taken_up_as_projects_or_steps():
    store = Store(":memory:")
    home = store.add_shelf("Home")
    idea = store.add_idea("Sourdough", "Winter project")
    store.set_shelf("ideas", idea, home)
    store.toggle_pin("ideas", idea)
    project = store.take_up_idea(idea)
    assert store.rows("SELECT title,notes,pinned,shelf_id FROM projects WHERE id=?", (project,))[0] == \
        {"title": "Sourdough", "notes": "Winter project", "pinned": 1, "shelf_id": home}
    assert store.rows("SELECT project_id FROM ideas")[0]["project_id"] == project
    other = store.add_idea("Fix the bike")
    store.take_up_idea(other, project)
    assert store.rows("SELECT title FROM project_tasks WHERE project_id=?", (project,))[0]["title"] == "Fix the bike"
    store.undo()
    assert not store.rows("SELECT id FROM project_tasks")
    assert store.rows("SELECT taken_day FROM ideas WHERE id=?", (other,))[0]["taken_day"] is None


async def test_nesting_and_ideas_from_the_keyboard():
    store = Store(":memory:")
    project = store.add_project("Move flat")
    pack = store.add_task(project, "Pack")
    boxes = store.add_task(project, "Get boxes")
    app = Tuido(store)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("f5", "enter", "down", "alt+right")
        assert store.rows("SELECT parent_id FROM project_tasks WHERE id=?", (boxes,))[0]["parent_id"] == pack
        assert app.row_id(app.query_one("#tasks", DataTable)) == boxes
        await pilot.press("alt+left")
        assert store.rows("SELECT parent_id FROM project_tasks WHERE id=?", (boxes,))[0]["parent_id"] is None
        await pilot.press("f6", "a")
        app.screen.query_one("#title", Input).value = "Sourdough"
        await pilot.click("#save")
        await pilot.pause()
        assert app.query_one("#items", DataTable).row_count == 1
        await pilot.click("#idea-step")
        await pilot.pause()
        await pilot.click("#save")
        await pilot.pause()
        assert store.rows("SELECT title FROM project_tasks WHERE project_id=? ORDER BY position DESC", (project,))[0]["title"] == "Sourdough"
        await pilot.click("#idea-project")
        await pilot.pause()
        assert store.rows("SELECT COUNT(*) AS n FROM projects")[0]["n"] == 2
    store.close()


async def test_previews_toggle_per_list_and_persist(tmp_path):
    path = tmp_path / "desk.sqlite3"
    store = Store(path)
    project = store.add_project("Thesis")
    store.add_task(project, "Outline")
    store.add_idea("Sourdough", "Winter project")
    app = Tuido(store)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("f5")
        cell = lambda: str(app.query_one("#items", DataTable).get_row_at(0)[0])
        assert "→ Outline" in cell()
        await pilot.press("d")
        assert "Outline" not in cell()
        await pilot.press("f6")
        assert "Winter project" in cell(), "each list keeps its own setting"
        await pilot.click("#sidebar-options")
        await pilot.pause()
        await pilot.click("#sidebar-previews")
        await pilot.pause()
        assert "Winter project" not in cell()
        await pilot.press("ctrl+z")
        assert not store.previews("ideas"), "undo leaves view settings alone"
    store.close()
    store = Store(path)
    assert not store.previews("projects") and not store.previews("ideas")
    store.close()


def test_a_task_can_be_due_and_late_ones_are_found(tmp_path):
    from tuido.store import Store
    store = Store(tmp_path / "due.sqlite3")
    project = store.add_project("Kiln")
    task = store.add_task(project, "Order clay")
    done = store.add_task(project, "Sweep")
    store.set_due(task, "2026-11-02")
    store.set_due(done, "2026-11-01")
    store.cycle_task(done)
    store.cycle_task(done)                                    # finished: never late
    assert [r["title"] for r in store.overdue(project, "2026-11-04")] == ["Order clay"]
    assert store.overdue(project, "2026-11-02") == []          # due today isn't late yet
    store.set_due(task, None)
    assert store.overdue(project, "2026-11-04") == []
    store.undo()                                              # one undo step: due again
    assert [r["title"] for r in store.overdue(project, "2026-11-04")] == ["Order clay"]
    store.close()
