from copy import deepcopy
from datetime import date
import json

from textual.widgets import DataTable, Input, Select, Static, TextArea, Tree

from tuido.app import Tuido
from tuido.demo import DEMO_SYLLABUS
from tuido.store import Store


async def test_two_book_sources_types_and_layout_after_switching():
    syllabus = {
        "version": 1, "id": "two-books", "title": "Geology foundations",
        "resources": [
            {"id": "general", "title": "General Geology", "type": "book", "chapters": [
                {"id": "earth", "title": "Kapitel 1: System Erde"},
                {"id": "plates", "title": "Kapitel 2: Plattentektonik"}]},
            {"id": "structural", "title": "Structural Geology", "type": "book", "chapters": [
                {"id": "stress", "title": "Chapter 1: Stress and strain"}]},
        ],
        "modules": [{"id": "foundations", "title": "Earth systems", "kind": "module", "children": [
            {"id": "earth-reading", "title": "Read: System Erde", "kind": "read",
             "resource": "general", "chapter": "earth"},
            {"id": "plate-exercises", "title": "Plate boundary problems", "kind": "exercise",
             "resource": "general", "chapter": "plates"},
            {"id": "stress-reading", "title": "Read: Stress and strain", "kind": "read",
             "resource": "structural", "chapter": "stress"},
        ]}],
    }
    store = Store(":memory:")
    store.import_syllabus(syllabus)
    app = Tuido(store)
    async with app.run_test(size=(140, 40)) as pilot:
        table = app.query_one("#syllabus", DataTable)
        for node in app.learning_nodes.values():
            title, kind = table.get_row(str(node["id"]))
            assert kind.plain == node["kind"] + ("\noptional" if node["optional"] else "")
            assert kind.justify == "right"
            if node["resource_uid"]:
                source = next(r for r in syllabus["resources"] if r["id"] == node["resource_uid"])
                assert source["title"] not in title.plain
                assert "Read:" not in title.plain
        # Selection reveals the source without repeating it throughout the list.
        app.query_one("#syllabus").focus()
        sources_seen = set()
        for node in app.learning_nodes.values():
            if node["resource_uid"] and node["resource_uid"] not in sources_seen:
                table.move_cursor(row=table.get_row_index(str(node["id"])))
                await pilot.pause()
                source = next(r for r in syllabus["resources"] if r["id"] == node["resource_uid"])
                assert "Source: " + source["title"] in app.query_one("#learning-info", Static).render().plain
                sources_seen.add(node["resource_uid"])
        assert len(sources_seen) == 2
        table.move_cursor(row=0)
        await pilot.pause()
        assert "Source:" not in app.query_one("#learning-info", Static).render().plain
        for width in (80, 140, 60):
            await pilot.press("f2")
            await pilot.resize_terminal(width, 40)
            await pilot.press("f4", "f1")
            await pilot.pause()
            assert table.filled_width == table.size.width
            assert sum(c.width + 2 * table.cell_padding for c in table.ordered_columns) <= table.size.width
            assert table.ordered_columns[0].width >= 10
        await pilot.press("f2")
        chapters = app.query_one("#chapters", DataTable)
        assert chapters.get_row_at(1)[1].plain == syllabus["resources"][0]["chapters"][1]["title"]
    store.close()


async def test_visuals_stay_inside_app_and_show_art_progress_and_dependencies(monkeypatch):
    def no_browser(*args, **kwargs):
        raise AssertionError("Visuals must stay inside TuiDo")
    monkeypatch.setattr("webbrowser.open", no_browser)
    store = Store(":memory:")
    syllabus = deepcopy(DEMO_SYLLABUS)
    syllabus["ascii"] = " /\\\n/__\\"
    path_id = store.import_syllabus(syllabus)
    app = Tuido(store)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("v")
        tree = app.screen.query_one("#visual-tree", Tree)
        assert len(tree.root.children) == 3
        assert "After: Find your question" in tree.root.children[1].label.plain
        assert app.screen.path["ascii_art"] == syllabus["ascii"]
        await pilot.press("escape", "n", "space", "space", "v")
        assert store.learning_snapshot(path_id)[2] == app.screen.states
        assert 2 in app.screen.states.values()
        await pilot.click("#close-visual")
        assert app.screen is app.screen_stack[0]
    store.close()


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
