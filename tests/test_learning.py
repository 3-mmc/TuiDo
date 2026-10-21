from copy import deepcopy
from datetime import date
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from tuido.demo import DEMO_SYLLABUS
from tuido.store import Store
from tuido.syllabus import SyllabusError, validate_syllabus
from tuido.visuals import render_path_html


@pytest.fixture
def learning():
    store = Store(":memory:")
    path_id = store.import_syllabus(deepcopy(DEMO_SYLLABUS))
    yield store, path_id
    store.close()


def activity(store, uid, path_id=None):
    rows = store.rows("SELECT * FROM activities WHERE uid=?" + (" AND path_id=?" if path_id else ""), (uid, path_id) if path_id else (uid,))
    return rows[0]


def test_shared_chapters_and_optional_work(learning):
    store, path_id = learning
    reading = activity(store, "question-reading")
    store.cycle_chapter(reading["chapter_id"])
    assert store.learning_snapshot(path_id)[2][reading["id"]] == 1
    store.cycle_activity(reading["id"])
    assert store.rows("SELECT reading FROM chapters WHERE id=?", (reading["chapter_id"],))[0]["reading"] == 2
    second = deepcopy(DEMO_SYLLABUS)
    second["id"] = "another:path"
    second_id = store.import_syllabus(second)
    assert store.learning_snapshot(second_id)[2][activity(store, "question-reading", second_id)["id"]] == 2
    assert len(store.rows("SELECT * FROM books")) == 1
    for uid in ("lecture", "retrieval-reading", "retrieval-exercise"):
        node = activity(store, uid, path_id)
        with store.change():
            store._set_activity(node["id"], 2)
    states = store.learning_snapshot(path_id)[2]
    assert states[activity(store, "practice", path_id)["id"]] == 2
    assert states[activity(store, "extra", path_id)["id"]] == 0


def test_import_revision_preserves_progress_evidence_and_archives(learning):
    store, path_id = learning
    node = activity(store, "question-exercise")
    store.cycle_activity(node["id"])
    skill_id = store.rows("SELECT id FROM skills ORDER BY id")[0]["id"]
    store.save_skill(skill_id, 3, "I framed a question and wrote an explanation.")
    revised = deepcopy(DEMO_SYLLABUS)
    revised["title"] = "Updated path"
    revised["modules"][0]["children"][1]["title"] = "Reworded instruction"
    revised["modules"][1]["children"] = revised["modules"][1]["children"][:-1]
    summary = store.import_preview(revised)
    assert summary["archived"] == 1
    assert store.import_syllabus(revised) == path_id
    assert activity(store, "question-exercise")["status"] == 1
    assert activity(store, "extra")["active"] == 0
    skill = store.rows("SELECT * FROM skills WHERE id=?", (skill_id,))[0]
    assert skill["level"] == 3
    assert skill["evidence"].startswith("I framed")
    assert store.undo()
    assert activity(store, "extra")["active"] == 1
    assert store.rows("SELECT title FROM paths")[0]["title"] == DEMO_SYLLABUS["title"]


def test_changed_meaning_rolls_back_entire_import(learning):
    store, _ = learning
    before = store.export()
    revised = deepcopy(DEMO_SYLLABUS)
    revised["title"] = "Should roll back"
    revised["resources"][0]["title"] = "Also should roll back"
    revised["modules"][0]["children"][0]["chapter"] = "retrieval"
    with pytest.raises(SyllabusError, match="meaning"):
        store.import_syllabus(revised)
    assert store.export() == before


@pytest.mark.parametrize("mutate", [
    lambda d: d["modules"].append(deepcopy(d["modules"][0])),
    lambda d: d["modules"][0].update(requires=["missing"]),
    lambda d: d["modules"][0].update(requires=["practice"]),
    lambda d: d["modules"][0]["children"][0].update(requires=["orientation"]),
    lambda d: d["modules"][0]["children"][0].update(resource="missing"),
    lambda d: d["modules"][0]["children"][0].update(resource=[]),
    lambda d: d["modules"][0]["children"][0].update(chapter="missing"),
    lambda d: d["skills"][0].update(criteria=["missing"]),
    lambda d: d["resources"][0].update(url="javascript:alert(1)"),
    lambda d: d.update(title="ANSI\x1b[31m"),
    lambda d: d.update(ascii_piece='seed\" onclick=\"x'),
])
def test_invalid_import_is_rejected_before_changes(mutate):
    data = deepcopy(DEMO_SYLLABUS)
    mutate(data)
    with pytest.raises(SyllabusError):
        validate_syllabus(data)


def test_linked_activity_completion_and_undo(learning):
    store, path_id = learning
    node = activity(store, "question-reading")
    habit = store.add_habit("Read")
    bullet = store.add_bullet(date.today().isoformat(), "Read", habit_id=habit, activity_id=node["id"])
    store.toggle_bullet(bullet)
    assert store.learning_snapshot(path_id)[2][node["id"]] == 2
    assert store.rows("SELECT amount FROM checkins")[0]["amount"] == 1
    assert store.undo()
    assert store.learning_snapshot(path_id)[2][node["id"]] == 0
    assert not store.rows("SELECT * FROM checkins")
    assert store.rows("SELECT done FROM bullets")[0]["done"] == 0


def test_skill_assessment_requires_evidence_and_is_not_auto_awarded(learning):
    store, _ = learning
    skill_id = store.rows("SELECT id FROM skills LIMIT 1")[0]["id"]
    with pytest.raises(ValueError, match="evidence"):
        store.save_skill(skill_id, 3, "")
    for node in store.rows("SELECT id FROM activities WHERE kind != 'module'"):
        with store.change():
            store._set_activity(node["id"], 2)
    assert store.rows("SELECT level FROM skills WHERE id=?", (skill_id,))[0]["level"] == 0
    store.save_skill(skill_id, 2, "Exercise solutions")
    assert store.rows("SELECT level FROM skills WHERE id=?", (skill_id,))[0]["level"] == 2


def test_export_roundtrip_and_safe_visuals(learning):
    store, path_id = learning
    exported = store.export_syllabus(path_id)
    validate_syllabus(exported)
    other = Store(":memory:")
    other.import_syllabus(exported)
    assert other.export_syllabus(path_id) == exported
    exported["title"] = '<script>alert("x")</script>'
    exported["modules"][0]["notes"] = '<img src=x onerror="alert(1)">'
    store.import_syllabus(exported)
    html = render_path_html(store, path_id)
    assert '<script>alert("x")</script>' not in html
    assert '<img src=x' not in html
    assert "&lt;script&gt;" in html
    assert "securityLevel:'strict'" in html
    assert 'piece="seed-germination"' in html
    assert "https://www.ascii-magic.com/ascii/ascii.js" in html
    other.close()


def test_existing_database_migration_keeps_books(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE books(id INTEGER PRIMARY KEY,title TEXT NOT NULL,textbook INTEGER DEFAULT 0);
        INSERT INTO books VALUES(1,'Existing book',1);
        CREATE TABLE bullets(id INTEGER PRIMARY KEY,day TEXT,text TEXT,note INTEGER DEFAULT 0,
            done INTEGER DEFAULT 0,migrated INTEGER DEFAULT 0,credited INTEGER DEFAULT 0,
            chapter_id INTEGER,habit_id INTEGER);
        INSERT INTO bullets(day,text) VALUES('2026-10-20','Keep this');
    """)
    db.close()
    store = Store(path)
    assert store.rows("SELECT title FROM books")[0]["title"] == "Existing book"
    assert store.rows("SELECT activity_id,text FROM bullets")[0] == {"activity_id": None, "text": "Keep this"}
    store.close()
    reopened = Store(path)
    assert len(reopened.rows("SELECT * FROM books")) == 1
    reopened.close()


def test_manually_linked_library_chapter_exports_and_shares_progress():
    store = Store(":memory:")
    store.add_book("My book", ["Chapter A", "Chapter B"], True)
    chapter_id = store.rows("SELECT id FROM chapters LIMIT 1")[0]["id"]
    path_id = store.add_path("A path")
    read = store.add_activity(path_id, "Read chapter", chapter_id=chapter_id)
    exercise = store.add_activity(path_id, "Practise chapter", kind="exercise", chapter_id=chapter_id)
    store.cycle_activity(read)
    store.cycle_activity(read)
    assert store.learning_snapshot(path_id)[2][read] == 2
    assert store.learning_snapshot(path_id)[2][exercise] == 0
    store.cycle_activity(exercise)
    assert store.rows("SELECT exercises FROM chapters WHERE id=?", (chapter_id,))[0]["exercises"] == 1
    validate_syllabus(store.export_syllabus(path_id))
    store.close()


def test_cli_preview_does_not_create_database_and_apply_does(tmp_path):
    source = tmp_path / "syllabus.json"
    source.write_text(json.dumps(DEMO_SYLLABUS))
    database = tmp_path / "journal.sqlite3"
    command = [sys.executable, "-m", "tuido", "--db", str(database), "--import-syllabus", str(source)]
    preview = subprocess.run(command, capture_output=True, text=True)
    assert preview.returncode == 0, preview.stderr
    assert not database.exists()
    assert "Preview only" in preview.stdout
    applied = subprocess.run([*command, "--apply"], capture_output=True, text=True)
    assert applied.returncode == 0, applied.stderr
    store = Store(database)
    assert len(store.rows("SELECT * FROM paths")) == 1
    store.close()
