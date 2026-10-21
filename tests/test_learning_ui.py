from copy import deepcopy
from datetime import date
import json

from textual.widgets import DataTable, Input, Select, TextArea

from tuido.app import Tuido
from tuido.demo import DEMO_SYLLABUS
from tuido.store import Store


async def test_continue_plan_and_complete_from_today():
    store = Store(":memory:")
    path_id = store.import_syllabus(deepcopy(DEMO_SYLLABUS))
    app = Tuido(store)
    async with app.run_test(size=(140, 40)) as pilot:
        assert app.mode == "paths"
        await pilot.press("n")
        selected = app.row_id(app.query_one("#syllabus", DataTable))
        assert app.learning_nodes[selected]["uid"] == "question-reading"
        await pilot.press("p")
        await pilot.click("#save")
        await pilot.pause()
        app.query_one("#bullets").focus()
        await pilot.press("enter")
        assert store.learning_snapshot(path_id)[2][selected] == 2
        await pilot.press("n")
        next_id = app.row_id(app.query_one("#syllabus", DataTable))
        assert app.learning_nodes[next_id]["uid"] == "question-exercise"
        await pilot.press("space", "space", "n")
        next_id = app.row_id(app.query_one("#syllabus", DataTable))
        assert app.learning_nodes[next_id]["uid"] == "lecture"
        await pilot.press("f2")
        assert app.query_one("#chapters").display
        assert not app.query_one("#syllabus").display
    store.close()


async def test_import_preview_cancel_and_confirm(tmp_path):
    source = tmp_path / "syllabus.json"
    source.write_text(json.dumps(DEMO_SYLLABUS))
    store = Store(":memory:")
    app = Tuido(store)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("ctrl+o")
        app.screen.query_one("#title", Input).value = str(source)
        await pilot.click("#save")
        await pilot.pause()
        assert not store.rows("SELECT * FROM paths")
        await pilot.click("#cancel-import")
        await pilot.press("ctrl+o")
        app.screen.query_one("#title", Input).value = str(source)
        await pilot.click("#save")
        await pilot.pause()
        await pilot.click("#confirm-import")
        await pilot.pause()
        assert app.mode == "paths"
        assert len(store.rows("SELECT * FROM paths")) == 1
        await pilot.press("ctrl+z")
        assert not store.rows("SELECT * FROM paths")
    store.close()


async def test_skill_evidence_validation_and_recording():
    store = Store(":memory:")
    store.import_syllabus(deepcopy(DEMO_SYLLABUS))
    app = Tuido(store)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("f4", "enter")
        app.screen.query_one("#level", Select).value = 3
        await pilot.click("#save")
        assert store.rows("SELECT MAX(level) AS level FROM skills")[0]["level"] == 0
        await pilot.pause(0.3)
        app.screen.query_one("#evidence", TextArea).text = "Solved a fresh problem and kept the solution."
        await pilot.click("#save")
        await pilot.pause()
        assert store.rows("SELECT MAX(level) AS level FROM skills")[0]["level"] == 3
        assert app.query_one("#skills-detail").display
    store.close()


async def test_path_collapse_and_narrow_layout():
    store = Store(":memory:")
    store.import_syllabus(deepcopy(DEMO_SYLLABUS))
    app = Tuido(store)
    async with app.run_test(size=(80, 30)) as pilot:
        table = app.query_one("#syllabus", DataTable)
        expanded = table.row_count
        await pilot.press("enter", "enter")
        assert table.row_count < expanded
        await pilot.press("enter")
        assert table.row_count == expanded
        await pilot.resize_terminal(60, 30)
        await pilot.pause()
        assert app.query_one("#contents").region.right <= 60
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert app.query_one("#journal").region.right <= 60
        assert not app.query_one("#library").display
    store.close()


async def test_manual_path_module_and_activity():
    store = Store(":memory:")
    app = Tuido(store)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press("f1", "a")
        app.screen.query_one("#title", Input).value = "Statistics"
        await pilot.click("#save")
        await pilot.pause()
        app.add_activity()
        await pilot.pause()
        app.screen.query_one("#title", Input).value = "Foundations"
        await pilot.click("#save")
        await pilot.pause()
        app.query_one("#syllabus").focus()
        await pilot.press("c")
        app.screen.query_one("#title", Input).value = "Try a problem"
        app.screen.query_one("#kind", Select).value = "exercise"
        await pilot.click("#save")
        await pilot.pause()
        assert len(store.rows("SELECT * FROM activities")) == 2
        child = store.rows("SELECT * FROM activities WHERE kind='exercise'")[0]
        assert child["parent_id"] is not None
    store.close()
