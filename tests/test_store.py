import json

import pytest

from tuido.store import Store


def test_linked_completion_is_atomic_and_undo_survives_restart(tmp_path):
    path = tmp_path / "journal.sqlite3"
    store = Store(path)
    book = store.add_book("Algebra", ["Vectors"], True)
    chapter = store.rows("SELECT id FROM chapters")[0]["id"]
    habit = store.add_habit("Read")
    bullet = store.add_bullet("2026-10-20", "Read vectors", chapter, habit)
    store.toggle_bullet(bullet)
    assert store.rows("SELECT reading FROM chapters")[0]["reading"] == 2
    assert store.rows("SELECT amount FROM checkins")[0]["amount"] == 1
    assert store.undo()
    store.close()
    reopened = Store(path)
    assert reopened.rows("SELECT done FROM bullets")[0]["done"] == 0
    assert reopened.rows("SELECT reading FROM chapters")[0]["reading"] == 0
    assert reopened.rows("SELECT * FROM checkins") == []
    reopened.delete("books", book)
    assert not reopened.rows("SELECT * FROM chapters")
    assert reopened.rows("SELECT chapter_id FROM bullets")[0]["chapter_id"] is None
    assert reopened.undo()
    assert reopened.rows("SELECT chapter_id FROM bullets")[0]["chapter_id"] == chapter
    reopened.close()


def test_reopening_bullet_does_not_duplicate_habit_credit():
    store = Store(":memory:")
    habit = store.add_habit("Read")
    bullet = store.add_bullet("2026-10-20", "Read", habit_id=habit)
    for _ in range(3):
        store.toggle_bullet(bullet)
    assert store.rows("SELECT amount FROM checkins")[0]["amount"] == 1
    store.close()


def test_migration_keeps_history_without_duplicating_tasks():
    store = Store(":memory:")
    bullet = store.add_bullet("2026-10-19", "Library")
    assert store.migrate(bullet, "2026-10-20")
    assert not store.migrate(bullet, "2026-10-20")
    assert len(store.rows("SELECT * FROM bullets")) == 2
    assert store.rows("SELECT migrated FROM bullets WHERE id=?", (bullet,))[0]["migrated"] == 1
    assert store.undo()
    assert len(store.rows("SELECT * FROM bullets")) == 1
    assert store.rows("SELECT migrated FROM bullets")[0]["migrated"] == 0
    store.close()


def test_failed_action_rolls_back_and_does_not_add_undo_step():
    store = Store(":memory:")
    with pytest.raises(Exception):
        with store.change():
            store.db.execute("INSERT INTO books(title) VALUES ('Temporary')")
            store.db.execute("INSERT INTO chapters(book_id,title,position) VALUES (999,'Bad',0)")
    assert store.rows("SELECT * FROM books") == []
    assert not store.undo()
    store.close()


def test_counts_notes_and_export():
    store = Store(":memory:")
    habit = store.add_habit("Exercise", "minutes", 30, 3)
    store.checkin(habit, "2026-10-20", 20)
    store.checkin(habit, "2026-10-20", 15)
    store.checkin(habit, "2026-10-20", -50)
    assert store.rows("SELECT amount FROM checkins")[0]["amount"] == 0
    note = store.add_bullet("2026-10-20", "- A thought")
    store.toggle_bullet(note)
    assert store.rows("SELECT done FROM bullets")[0]["done"] == 0
    data = json.loads(store.export())
    assert data["bullets"][0]["text"] == "A thought"
    assert data["habits"][0]["weekly_goal"] == 3
    store.close()


def test_habit_groups_roll_up_without_duplicate_credit_and_undo(tmp_path):
    path = tmp_path / "habits.sqlite3"
    store = Store(path)
    creative = store.add_habit("Creative")
    dj = store.add_habit("DJing", daily_goal=3, goal_period="week", parent_id=creative)
    painting = store.add_habit("Painting", parent_id=creative)
    store.checkin(dj, "2026-10-19", 2)
    store.checkin(painting, "2026-10-19", 1)
    bullet = store.add_bullet("2026-10-20", "DJ", habit_id=dj)
    store.toggle_bullet(bullet)
    store.toggle_bullet(bullet)
    store.toggle_bullet(bullet)
    assert store.habit_counts(creative) == {"2026-10-19": 3, "2026-10-20": 1}
    assert store.habit_counts(dj) == {"2026-10-19": 2, "2026-10-20": 1}
    store.set_checkin(dj, "2026-10-19", 0)
    assert store.habit_counts(creative)["2026-10-19"] == 1
    assert store.undo()
    store.close()
    store = Store(path)
    assert store.habit_counts(creative)["2026-10-19"] == 3
    store.delete("habits", creative)
    assert store.rows("SELECT parent_id FROM habits WHERE id=?", (dj,))[0]["parent_id"] is None
    assert store.habit_counts(dj)["2026-10-19"] == 2
    assert store.undo()
    assert store.habit_counts(creative)["2026-10-19"] == 3
    store.close()


def test_habit_edit_rejects_cycles_and_incompatible_units():
    store = Store(":memory:")
    parent = store.add_habit("Creative")
    child = store.add_habit("DJing", parent_id=parent)
    with pytest.raises(ValueError, match="ancestor"):
        store.edit_habit(parent, "Creative", "sessions", 1, 7, parent_id=child)
    with pytest.raises(ValueError, match="same unit"):
        store.edit_habit(parent, "Creative", "minutes", 30, 7)
    with pytest.raises(ValueError, match="same unit"):
        store.add_habit("Painting", "minutes", parent_id=parent)
    store.edit_habit(child, "DJ practice", "sessions", 10, 7, "week", parent)
    assert store.rows("SELECT daily_goal,goal_period FROM habits WHERE id=?", (child,))[0] == {"daily_goal": 10, "goal_period": "week"}
    assert store.undo()
    assert store.rows("SELECT title FROM habits WHERE id=?", (child,))[0]["title"] == "DJing"
    store.close()


def test_old_habit_database_migrates_preserving_targets(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE habits(id INTEGER PRIMARY KEY,title TEXT NOT NULL,unit TEXT NOT NULL DEFAULT 'sessions',daily_goal INTEGER NOT NULL DEFAULT 1 CHECK(daily_goal>0),weekly_goal INTEGER NOT NULL DEFAULT 7 CHECK(weekly_goal BETWEEN 1 AND 7))")
        db.execute("INSERT INTO habits(title,daily_goal,weekly_goal) VALUES ('Read',30,3)")
    store = Store(path)
    habit = store.rows("SELECT * FROM habits")[0]
    assert (habit["daily_goal"], habit["weekly_goal"], habit["goal_period"], habit["parent_id"]) == (30, 3, "day", None)
    store.close()


def test_future_habit_plans_require_confirmation_when_date_arrives(monkeypatch):
    from datetime import date
    class Clock(date):
        current = date(2026, 10, 22)
        @classmethod
        def today(cls):
            return cls.current
    monkeypatch.setattr("tuido.store.date", Clock)
    store = Store(":memory:")
    habit = store.add_habit("DJing", daily_goal=3, goal_period="week")
    store.set_checkin(habit, "2026-10-23", 2)
    assert store.habit_counts(habit, planned=False) == {}
    assert store.habit_counts(habit, planned=True) == {"2026-10-23": 2}
    Clock.current = date(2026, 10, 23)
    assert store.habit_counts(habit, planned=False) == {}
    store.set_checkin(habit, "2026-10-23", 1)
    assert store.habit_counts(habit, planned=False) == {"2026-10-23": 1}
    assert store.habit_counts(habit, planned=True) == {}
    assert store.undo()
    assert store.habit_counts(habit, planned=True) == {"2026-10-23": 2}
    store.close()


def test_habit_sidebar_groups_nested_children_and_sorts_siblings(tmp_path):
    store = Store(tmp_path / "order.sqlite3")
    creative = store.add_habit("Creative")
    exercise = store.add_habit("Exercise")
    painting = store.add_habit("Painting", parent_id=creative)
    dj = store.add_habit("DJing", parent_id=creative)
    mixing = store.add_habit("Mixing", parent_id=dj)
    ids = lambda: [row["id"] for row in store.sidebar_items("habits")]
    assert ids() == [creative, painting, dj, mixing, exercise]
    assert [row["sidebar_depth"] for row in store.sidebar_items("habits")] == [0, 1, 1, 2, 0]
    store.set_sidebar_sort("habits", "name")
    assert ids() == [creative, dj, mixing, painting, exercise]
    store.set_sidebar_sort("habits", "name-desc")
    assert ids() == [exercise, creative, painting, dj, mixing]
    assert store.move_sidebar_item("habits", creative, -1)
    assert store.sidebar_sort("habits") == "custom"
    assert ids() == [creative, painting, dj, mixing, exercise]
    assert store.undo()
    assert store.sidebar_sort("habits") == "name-desc"
    assert ids() == [exercise, creative, painting, dj, mixing]
    assert store.move_sidebar_item("habits", dj, -1)
    assert ids() == [exercise, creative, dj, mixing, painting]
    assert not store.move_sidebar_item("habits", mixing, -1)
    store.checkin(dj, "2026-10-22", 1)
    assert store.habit_counts(creative)["2026-10-22"] == 1
    store.close()
    store = Store(tmp_path / "order.sqlite3")
    assert [row["id"] for row in store.sidebar_items("habits")] == [exercise, creative, dj, mixing, painting]
    assert store.sidebar_sort("habits") == "custom"
    store.close()


@pytest.mark.parametrize("table", ["books", "paths", "skills", "habits"])
def test_sidebar_sort_custom_order_and_new_items(tmp_path, table):
    store = Store(tmp_path / "sidebar.sqlite3")
    path = store.add_path("Skill path") if table == "skills" else None
    create = {"books": lambda title: store.add_book(title, []), "paths": store.add_path,
              "skills": lambda title: store.add_skill(path, title), "habits": store.add_habit}[table]
    first, second, third = [create(title) for title in ("Zulu", "alpha", "Beta")]
    ids = lambda: [row["id"] for row in store.sidebar_items(table)]
    store.set_sidebar_sort(table, "name")
    assert ids() == [second, third, first]
    assert store.move_sidebar_item(table, third, -1)
    assert ids() == [third, second, first]
    assert store.sidebar_sort(table) == "custom"
    fourth = create("New")
    assert ids() == [third, second, first, fourth]
    store.set_sidebar_sort(table, "newest")
    assert ids() == [fourth, third, second, first]
    store.set_sidebar_sort(table, "oldest")
    assert ids() == [first, second, third, fourth]
    store.set_sidebar_sort(table, "custom")
    assert ids() == [third, second, first, fourth]
    assert any(row["collection"] == table for row in json.loads(store.export())["sidebar_preferences"])
    store.close()
