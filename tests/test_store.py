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
