"""The desk on a canvas: its tree, marking, planning, adding, continuing, undo, and watching the
file for changes made beside it. Each test has its own database; none touches yours."""
import re
import sqlite3
import time
from datetime import date

import pytest

from tuido import treecanvas as tc
from tuido.canvas import Desk, boxes
from tuido.store import Store

ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


@pytest.fixture
def desk(tmp_path):
    store = Store(tmp_path / "desk.sqlite3")
    store.seed_demo()
    yield store
    store.close()


def canvas(store, path=None, watch=0):
    return tc.Canvas("", tc.options(provider=Desk(store, path, watch), backdrop="off", ease=1, glyphs="plain",
                                    colmax=40))


def press(c, *keys):
    result = None
    for k in keys:
        result = tc.apply(c, k, c.opts)
    return result


def screen(c, w=140, h=30):
    return [ANSI.sub("", l).rstrip() for l in c.frame(w, h, animate=False)[0]]


def find(c, *names):
    """Go to the node down this way of names (labels' beginnings)."""
    node = c.root
    ids = []
    for name in names:
        node = next(k for k in node.load() if k.label().startswith(name))
        ids.append(node.path)
    assert c.go(ids)
    return node


def test_the_desk_branches_into_its_sections_and_down(desk):
    c = canvas(desk)
    assert [k.name for k in c.root.load()] == ["Today", "Earlier pages", "Paths", "Library", "Habits", "Skills",
                                              "Projects", "Ideas"]
    book = find(c, "Library", "Linear Algebra")
    assert book.label() == "Linear Algebra  ▰▰▰◧▱▱▱▱"          # three read, one under way
    assert [k.name for k in book.load()][:2] == ["Systems of equations", "Row reduction"]
    assert book.source.mark(book.load()[0])[1] == "✓"
    thesis = find(c, "Projects", "Thesis chapter 2")
    assert thesis.source.mark(thesis)[1] == "★"                 # pinned
    outline = next(k for k in thesis.load() if k.name == "Outline")
    assert outline.is_dir and [k.name for k in outline.load()][0] == "List the three main arguments"
    laundry = next(k for k in find(c, "Projects", "Home").load() if k.name == "Laundry")
    assert laundry.label() == "Laundry · every 7 days · 9 days ago"
    habit = find(c, "Habits", "Read")
    assert re.fullmatch(r"Read  [■□· ]{7}", habit.label())
    assert "M " in habit.source.preview(habit)                   # the heatmap, a row a weekday
    assert "Earlier pages" in "".join(screen(c))


def test_enter_marks_things_and_opens_branches(desk):
    c = canvas(desk)
    today = find(c, "Today")
    task = next(k for k in today.load() if k.name == "Email supervisor")
    find(c, "Today", "Email supervisor")
    press(c, "\r")
    assert desk.rows("SELECT done FROM bullets WHERE text='Email supervisor'")[0]["done"] == 1
    screen(c)
    assert c.focus.source.mark(c.focus)[1] == "✓"
    chapter = find(c, "Library", "Linear Algebra", "Linear independence")
    press(c, "\r")
    assert desk.rows("SELECT reading FROM chapters WHERE title='Linear independence'")[0]["reading"] == 2
    find(c, "Habits", "Exercise")
    before = desk.habit_counts(desk.rows("SELECT id FROM habits WHERE title='Exercise'")[0]["id"]).get(date.today().isoformat(), 0)
    press(c, "\r")
    after = desk.habit_counts(desk.rows("SELECT id FROM habits WHERE title='Exercise'")[0]["id"]).get(date.today().isoformat(), 0)
    assert after == before + 1
    outline = find(c, "Projects", "Thesis chapter 2", "Outline")
    press(c, "\r")                                               # a branch: it opens, nothing marked
    assert c.focus.parent is outline
    assert desk.rows("SELECT status FROM project_tasks WHERE title='Outline'")[0]["status"] == 0


def test_plan_puts_it_in_today_linked_and_typed_lines_never_close_the_canvas(desk):
    c = canvas(desk)
    find(c, "Library", "Linear Algebra", "Eigenvalues")
    press(c, "\x10")
    assert c.asking[1] == "Read: Eigenvalues"                    # its title, to change if you like
    assert press(c, "\r") is None
    planned = desk.rows("SELECT * FROM bullets WHERE text='Read: Eigenvalues'")[0]
    assert planned["day"] == date.today().isoformat() and planned["chapter_id"]
    find(c, "Today")
    press(c, "\x0e")
    assert press(c, "\r") is None                                # nothing typed: nothing added, still open
    press(c, "\x0e", *"- remember the library", "\r")
    note = desk.rows("SELECT * FROM bullets WHERE text='remember the library'")[0]
    assert note["note"] == 1


def test_add_rename_delete_and_undo(desk):
    c = canvas(desk)
    find(c, "Projects", "Thesis chapter 2", "Send to supervisor")
    press(c, "\x0e", *"Book a meeting", "\r")
    step = desk.rows("SELECT * FROM project_tasks WHERE title='Book a meeting'")[0]
    assert step["parent_id"] is None                             # beside the step, in the project
    screen(c)                                                    # a frame takes the change in
    find(c, "Projects", "Thesis chapter 2", "Book a meeting")
    press(c, "\x05", "\x15", *"Book a meeting with Dr Lee", "\r")
    assert desk.rows("SELECT title FROM project_tasks WHERE id=?", (step["id"],))[0]["title"] == "Book a meeting with Dr Lee"
    press(c, "\x04", "y")
    assert not desk.rows("SELECT * FROM project_tasks WHERE id=?", (step["id"],))
    assert c.statuses["act"][1] == "gone"                        # it goes to dust
    press(c, "\x1a")
    assert desk.rows("SELECT title FROM project_tasks WHERE id=?", (step["id"],))
    screen(c)
    assert any(k.name == "Book a meeting with Dr Lee" for k in find(c, "Projects", "Thesis chapter 2").load())


def test_continue_flies_to_the_next_activity_ready(desk):
    c = canvas(desk)
    path = find(c, "Paths", "Learning to learn")
    press(c, "\x12")
    nxt = desk.next_activity(path.data["id"])
    assert c.focus.kind == "activity" and c.focus.data["id"] == nxt
    screen(c)
    assert c.focus.path in c.pulses                              # and it flashes as you land


def test_an_earlier_task_comes_forward_to_today(desk):
    c = canvas(desk)
    old = find(c, "Earlier pages", "yesterday", "Pick up library holds")
    press(c, "\x14")
    assert desk.rows("SELECT migrated FROM bullets WHERE id=?", (old.data["id"],))[0]["migrated"] == 1
    assert desk.rows("SELECT * FROM bullets WHERE text='Pick up library holds' AND day=?", (date.today().isoformat(),))


def test_focus_narrows_it_as_it_does_the_desk(desk):
    desk.set_view(focus=True)
    c = canvas(desk)
    assert [k.name for k in find(c, "Projects").load()] == ["Thesis chapter 2"]


def test_changes_made_beside_it_show(tmp_path):
    path = tmp_path / "desk.sqlite3"
    store = Store(path)
    store.add_project("Kiln shed")
    c = canvas(store, path, watch=0.05)
    projects = find(c, "Projects")
    other = sqlite3.connect(path)
    other.execute("INSERT INTO projects(title) VALUES ('Garden')")
    other.commit()
    other.close()
    for _ in range(60):
        time.sleep(0.05)
        if c.source.changed:
            break
    screen(c)
    assert [k.name for k in projects.load()] == ["Kiln shed", "Garden"]
    store.close()


def test_boxes_squeeze_and_show_progress():
    assert boxes([2, 1, 0]) == "▰◧▱"
    assert len(boxes([0] * 30)) == 8
    assert boxes([]) == ""
