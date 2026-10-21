from datetime import date, timedelta

from textual.widgets import DataTable, Input, Select, TextArea

from tuido.app import Tuido
from tuido.store import Store


async def test_book_selection_and_chapter_progress_persist(tmp_path):
    store = Store(tmp_path / "desk.sqlite3")
    store.add_book("First book", ["First chapter"])
    second = store.add_book("Second book", ["Second chapter"], True)
    app = Tuido(store)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("down", "enter", "space", "e")
        assert app.book_id == second
        chapter = store.rows("SELECT * FROM chapters WHERE book_id=?", (second,))[0]
        assert chapter["reading"] == 1
        assert chapter["exercises"] == 1
        await pilot.press("ctrl+z")
        assert store.rows("SELECT exercises FROM chapters WHERE book_id=?", (second,))[0]["exercises"] == 0
        library = app.query_one("#library").region
        contents = app.query_one("#contents").region
        journal = app.query_one("#journal").region
        assert library.right <= contents.x < contents.right <= journal.x
        assert journal.right <= 140
    store.close()


async def test_create_book_and_journal_using_keyboard():
    store = Store(":memory:")
    app = Tuido(store)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("f2", "a")
        app.screen.query_one("#title", Input).value = "My textbook"
        app.screen.query_one("#chapters", TextArea).text = "Introduction\nMethods\nResults"
        await pilot.click("#save")
        await pilot.pause()
        assert app.query_one("#chapters", DataTable).row_count == 3
        await pilot.press("ctrl+j")
        app.screen.query_one("#title", Input).value = "- Remember this"
        await pilot.click("#save")
        await pilot.pause()
        assert store.rows("SELECT note,text FROM bullets")[0] == {"note": 1, "text": "Remember this"}
        await pilot.press("question_mark")
        await pilot.press("escape")
    store.close()


async def test_linked_plan_completion_and_habits():
    store = Store(":memory:")
    store.add_book("Book", ["Chapter"])
    habit = store.add_habit("Read")
    app = Tuido(store)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("enter", "p")
        app.screen.query_one("#linked-habit", Select).value = habit
        await pilot.click("#save")
        await pilot.pause()
        app.query_one("#bullets").focus()
        await pilot.press("enter")
        assert store.rows("SELECT reading FROM chapters")[0]["reading"] == 2
        assert store.rows("SELECT amount FROM checkins")[0]["amount"] == 1
        await pilot.press("f3", "plus")
        assert app.mode == "habits"
        assert store.rows("SELECT amount FROM checkins")[0]["amount"] == 2
        assert app.query_one("#habit-detail").display
        await pilot.press("f2")
        assert app.mode == "books"
    store.close()


async def test_narrow_layout_and_history():
    store = Store(":memory:")
    yesterday = date.today() - timedelta(days=1)
    store.add_bullet(yesterday.isoformat(), "Old task")
    app = Tuido(store)
    async with app.run_test(size=(80, 24)) as pilot:
        assert not app.query_one("#journal").display
        assert app.query_one("#contents").region.right <= 80
        await pilot.press("ctrl+t", "ctrl+left")
        await pilot.pause()
        assert app.journal_day == yesterday
        app.query_one("#bullets").focus()
        await pilot.press("ctrl+y")
        assert len(store.rows("SELECT * FROM bullets WHERE day=?", (date.today().isoformat(),))) == 1
        await pilot.resize_terminal(140, 40)
        app.current_day()
        await pilot.pause()
        assert app.query_one("#bullets", DataTable).row_count == 1
    store.close()


async def test_wrapped_bullets_and_compact_columns():
    store = Store(":memory:")
    store.add_book("A long book title that should remain readable", ["Chapter"])
    store.add_bullet(date.today().isoformat(), "A long daily task that must wrap in the journal instead of disappearing off the right edge")
    app = Tuido(store)
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert app.query_one("#journal").region.right <= 80
        assert app.query_one("#contents").region.right <= app.query_one("#journal").region.x
        table = app.query_one("#bullets", DataTable)
        assert next(iter(table.rows.values())).height > 1
        await pilot.resize_terminal(60, 30)
        await pilot.pause()
        assert not app.query_one("#library").display
        assert app.query_one("#journal").region.right <= 60
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert app.query_one("#library").display
        assert app.query_one("#contents").region.right <= 60
    store.close()


async def test_habit_form_validation_and_amount_logging():
    store = Store(":memory:")
    app = Tuido(store)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("f3", "a")
        app.screen.query_one("#title", Input).value = "Exercise"
        app.screen.query_one("#weekly", Input).value = "9"
        await pilot.click("#save")
        assert not store.rows("SELECT * FROM habits")
        await pilot.pause(0.3)  # Let the button's normal click debounce expire.
        app.screen.query_one("#weekly", Input).value = "3"
        app.screen.query_one("#daily", Input).value = "30"
        app.screen.query_one("#unit", Input).value = "minutes"
        await pilot.click("#save")
        await pilot.pause()
        await pilot.click("#log-amount")
        app.screen.query_one("#daily", Input).value = "30"
        await pilot.click("#save")
        await pilot.pause()
        assert store.rows("SELECT amount FROM checkins")[0]["amount"] == 30
        assert store.rows("SELECT weekly_goal FROM habits")[0]["weekly_goal"] == 3
    store.close()


async def test_midnight_starts_a_fresh_page_without_moving_tasks(monkeypatch):
    today = date.today()
    store = Store(":memory:")
    store.add_bullet(today.isoformat(), "An unfinished task")
    app = Tuido(store)
    async with app.run_test(size=(120, 30)) as pilot:
        class Tomorrow(date):
            @classmethod
            def today(cls):
                return today + timedelta(days=1)
        monkeypatch.setattr("tuido.app.date", Tomorrow)
        app.check_date()
        await pilot.pause()
        assert app.journal_day == today + timedelta(days=1)
        assert app.query_one("#bullets", DataTable).row_count == 0
        assert store.rows("SELECT day FROM bullets")[0]["day"] == today.isoformat()
    store.close()
