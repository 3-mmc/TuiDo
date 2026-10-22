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


async def test_habits_edit_other_dates_and_separate_future_plans():
    from textual.widgets import Static
    store = Store(":memory:")
    habit = store.add_habit("DJing", daily_goal=3, goal_period="week")
    app = Tuido(store)
    async with app.run_test(size=(140, 48)) as pilot:
        await pilot.press("f3", "ctrl+left", "plus")
        past = date.today() - timedelta(days=1)
        assert store.habit_counts(habit)[past.isoformat()] == 1
        await pilot.click("#set-amount")
        app.screen.query_one("#amount", Input).value = "0"
        await pilot.click("#save")
        await pilot.pause()
        assert store.habit_counts(habit)[past.isoformat()] == 0
        app.current_day()
        await pilot.press("ctrl+right", "plus")
        future = date.today() + timedelta(days=1)
        assert app.journal_day == future
        assert store.habit_counts(habit)[future.isoformat()] == 1
        summary = str(app.query_one("#habit-summary", Static).render())
        assert "Planned" in summary and "0 / 3 sessions; 1 planned" in summary
        await pilot.click("#habit-date")
        app.screen.query_one("#day", Input).value = "2026-01-01"
        await pilot.click("#save")
        await pilot.pause()
        assert app.journal_day == date(2026, 1, 1)
    store.close()


async def test_create_and_edit_weekly_child_habit():
    store = Store(":memory:")
    parent = store.add_habit("Creative")
    app = Tuido(store)
    async with app.run_test(size=(140, 55)) as pilot:
        await pilot.press("f3", "a")
        app.screen.query_one("#title", Input).value = "DJing"
        app.screen.query_one("#daily", Input).value = "3"
        app.screen.query_one("#goal-period", Select).value = "week"
        app.screen.query_one("#parent", Select).value = parent
        await pilot.click("#save")
        await pilot.pause()
        child = app.habit_id
        assert child != parent
        await pilot.press("plus")
        assert store.habit_counts(parent)[date.today().isoformat()] == 1
        await pilot.click("#edit-habit")
        app.screen.query_one("#daily", Input).value = "4"
        await pilot.click("#save")
        await pilot.pause()
        assert store.rows("SELECT daily_goal,goal_period,parent_id FROM habits WHERE id=?", (child,))[0] == {"daily_goal": 4, "goal_period": "week", "parent_id": parent}
    store.close()


async def test_habit_controls_and_form_save_fit_small_terminal():
    from textual.widgets import Button
    store = Store(":memory:")
    store.add_habit("Creative")
    app = Tuido(store)
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.press("f3")
        assert not app.query_one("#journal").display
        nav = app.query_one("#habit-nav").region
        assert nav.right <= app.query_one("#contents").region.right
        await pilot.click("#habit-next")
        assert app.journal_day == date.today() + timedelta(days=1)
        app.habit_form(edit=True)
        await pilot.pause()
        save = app.screen.query_one("#save", Button)
        assert save.region.bottom < 30
        await pilot.click("#save")
        await pilot.pause()
        assert app.screen is app.screen_stack[0]
    store.close()


async def test_weekly_goal_hides_daily_schedule_and_ignores_blank_days():
    from textual.widgets import Label, Static
    store = Store(":memory:")
    app = Tuido(store)
    async with app.run_test(size=(100, 35)) as pilot:
        await pilot.press("f3", "a")
        form = app.screen
        form.query_one("#title", Input).value = "DJing"
        form.query_one("#daily", Input).value = "3"
        form.query_one("#weekly", Input).value = ""
        form.query_one("#goal-period", Select).value = "week"
        await pilot.pause()
        assert not form.query_one("#days-per-week").display
        assert "Total units per week" in str(form.query_one("#goal-amount-label", Label).render())
        assert "DJing: 3 sessions per week, on any days. No daily minimum." in str(form.query_one("#goal-preview", Static).render())
        await pilot.click("#save")
        await pilot.pause()
        habit = store.rows("SELECT * FROM habits")[0]
        assert habit["goal_period"] == "week" and habit["daily_goal"] == 3
        app.habit_form(edit=True)
        await pilot.pause()
        form = app.screen
        assert not form.query_one("#days-per-week").display
        form.query_one("#weekly", Input).value = "9"
        form.query_one("#goal-period", Select).value = "day"
        await pilot.pause()
        assert form.query_one("#days-per-week").display
        await pilot.click("#save")
        await pilot.pause()
        assert app.screen is form
        assert "Days per week" in str(form.query_one("#form-error", Static).render())
        form.query_one("#weekly", Input).value = "3"
        await pilot.pause()
        assert "each of 3 days per week" in str(form.query_one("#goal-preview", Static).render())
        await pilot.pause(0.3)  # Allow Save button click debounce after validation.
        await pilot.click("#save")
        await pilot.pause()
        habit = store.rows("SELECT * FROM habits")[0]
        assert habit["goal_period"] == "day" and habit["weekly_goal"] == 3
        app.habit_form(edit=True)
        await pilot.pause()
        form = app.screen
        form.query_one("#goal-period", Select).value = "week"
        form.query_one("#weekly", Input).value = "invalid hidden value"
        form.query_one("#daily", Input).value = "4"
        await pilot.pause()
        await pilot.click("#save")
        await pilot.pause()
        habit = store.rows("SELECT * FROM habits")[0]
        assert habit["goal_period"] == "week" and habit["daily_goal"] == 4
        assert habit["weekly_goal"] == 3
    store.close()


async def test_sidebar_sort_group_moves_selection_and_undo():
    from textual.widgets import Button
    store = Store(":memory:")
    creative = store.add_habit("Creative")
    exercise = store.add_habit("Exercise")
    painting = store.add_habit("Painting", parent_id=creative)
    dj = store.add_habit("DJing", parent_id=creative)
    app = Tuido(store)
    async with app.run_test(size=(100, 35)) as pilot:
        await pilot.press("f3")
        table = app.query_one("#items", DataTable)
        ids = lambda: [int(key.value) for key in table.rows]
        assert ids() == [creative, painting, dj, exercise]
        await pilot.click("#sidebar-options")
        app.screen.query_one("#sidebar-sort", Select).value = "name"
        await pilot.pause()
        assert ids() == [creative, dj, painting, exercise]
        assert app.habit_id == creative
        await pilot.click("#sidebar-options")
        assert app.screen.query_one("#move-up", Button).disabled
        await pilot.click("#move-down")
        await pilot.pause()
        assert ids() == [exercise, creative, dj, painting]
        assert app.habit_id == creative and app.row_id(table) == creative
        assert store.sidebar_sort("habits") == "custom"
        await pilot.press("ctrl+z")
        await pilot.pause()
        assert ids() == [creative, dj, painting, exercise]
        assert store.sidebar_sort("habits") == "name"
        table.move_cursor(row=table.get_row_index(str(painting)))
        await pilot.pause()
        await pilot.press("alt+up")
        await pilot.pause()
        assert ids() == [creative, painting, dj, exercise]
        assert app.habit_id == painting
        await pilot.press("f2")
        await pilot.click("#sidebar-options")
        assert app.screen.query_one("#move-up", Button).disabled
        assert app.screen.query_one("#move-down", Button).disabled
        await pilot.press("escape")
        await pilot.press("f3")
        assert store.sidebar_sort("habits") == "custom"
        await pilot.resize_terminal(60, 30)
        await pilot.pause()
        assert not app.query("#sidebar-sort")
        assert not app.query("#sidebar-order")
        assert app.query_one("#sidebar-options").region.right <= app.query_one("#library").region.right
        await pilot.click("#sidebar-options")
        assert app.screen.query_one("#sidebar-sort", Select).value == "custom"
        await pilot.press("escape")
    store.close()
