"""Local persistence. Each user action is one transaction and one undo step."""

from contextlib import contextmanager
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3

from .learning import LEARNING_TABLES, LearningStore


class Store(LearningStore):
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL,
                textbook INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS chapters (
                id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                title TEXT NOT NULL, position INTEGER NOT NULL,
                reading INTEGER NOT NULL DEFAULT 0 CHECK(reading BETWEEN 0 AND 2),
                exercises INTEGER NOT NULL DEFAULT 0 CHECK(exercises IN (0,1)));
            CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL, unit TEXT NOT NULL DEFAULT 'sessions',
                daily_goal INTEGER NOT NULL DEFAULT 1 CHECK(daily_goal > 0),
                weekly_goal INTEGER NOT NULL DEFAULT 7 CHECK(weekly_goal BETWEEN 1 AND 7));
            CREATE TABLE IF NOT EXISTS checkins (
                habit_id INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
                day TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount >= 0),
                PRIMARY KEY(habit_id, day));
            CREATE TABLE IF NOT EXISTS bullets (
                id INTEGER PRIMARY KEY, day TEXT NOT NULL, text TEXT NOT NULL,
                note INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0,
                migrated INTEGER NOT NULL DEFAULT 0, credited INTEGER NOT NULL DEFAULT 0,
                chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
                habit_id INTEGER REFERENCES habits(id) ON DELETE SET NULL);
        """)
        self.init_learning()
        self._undo: list[bytes] = []

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args)]

    @contextmanager
    def change(self):
        snapshot = self.db.serialize()
        with self.db:
            yield
        self._undo.append(snapshot)
        self._undo = self._undo[-50:]

    def undo(self):
        if not self._undo:
            return False
        # Backup writes restored pages to the actual file; deserialize alone would
        # detach this connection from its on-disk database.
        restored = sqlite3.connect(":memory:")
        try:
            restored.deserialize(self._undo.pop())
            restored.backup(self.db)
        finally:
            restored.close()
        return True

    def add_book(self, title, chapters, textbook=False):
        with self.change():
            book_id = self.db.execute("INSERT INTO books(title,textbook) VALUES (?,?)", (title, textbook)).lastrowid
            self.db.executemany("INSERT INTO chapters(book_id,title,position) VALUES (?,?,?)",
                                [(book_id, t, n) for n, t in enumerate(chapters)])
        return book_id

    def add_chapter(self, book_id, title):
        with self.change():
            position = self.db.execute("SELECT COALESCE(MAX(position),-1)+1 FROM chapters WHERE book_id=?", (book_id,)).fetchone()[0]
            self.db.execute("INSERT INTO chapters(book_id,title,position) VALUES (?,?,?)", (book_id, title, position))

    def cycle_chapter(self, chapter_id, exercises=False):
        with self.change():
            if exercises:
                self.db.execute("UPDATE chapters SET exercises=1-exercises WHERE id=?", (chapter_id,))
            else:
                self.db.execute("UPDATE chapters SET reading=(reading+1)%3 WHERE id=?", (chapter_id,))

    def add_habit(self, title, unit="sessions", daily_goal=1, weekly_goal=7):
        with self.change():
            return self.db.execute("INSERT INTO habits(title,unit,daily_goal,weekly_goal) VALUES (?,?,?,?)",
                                   (title, unit, daily_goal, weekly_goal)).lastrowid

    def _increment(self, habit_id, day, amount):
        if amount >= 0:
            self.db.execute("""INSERT INTO checkins VALUES (?,?,?) ON CONFLICT(habit_id,day)
                            DO UPDATE SET amount=amount+excluded.amount""", (habit_id, day, amount))
        else:
            self.db.execute("UPDATE checkins SET amount=MAX(0,amount+?) WHERE habit_id=? AND day=?", (amount, habit_id, day))

    def checkin(self, habit_id, day, amount):
        with self.change():
            self._increment(habit_id, day, amount)

    def add_bullet(self, day, text, chapter_id=None, habit_id=None, activity_id=None):
        note = text.startswith("- ")
        with self.change():
            return self.db.execute("INSERT INTO bullets(day,text,note,chapter_id,habit_id,activity_id) VALUES (?,?,?,?,?,?)",
                                   (day, text[2:] if note else text, note, chapter_id, habit_id, activity_id)).lastrowid

    def toggle_bullet(self, bullet_id):
        bullet = self.rows("SELECT * FROM bullets WHERE id=?", (bullet_id,))[0]
        if bullet["note"] or bullet["migrated"]:
            return
        with self.change():
            self.db.execute("UPDATE bullets SET done=1-done WHERE id=?", (bullet_id,))
            # Reopening a task does not erase independent progress. Undo reverses
            # the complete linked action if it was accidental.
            if not bullet["done"] and not bullet["credited"]:
                if bullet["activity_id"]:
                    self._set_activity(bullet["activity_id"], 2)
                if bullet["chapter_id"]:
                    self.db.execute("UPDATE chapters SET reading=2 WHERE id=?", (bullet["chapter_id"],))
                if bullet["habit_id"]:
                    self._increment(bullet["habit_id"], bullet["day"], 1)
                self.db.execute("UPDATE bullets SET credited=1 WHERE id=?", (bullet_id,))

    def migrate(self, bullet_id, target_day):
        bullet = self.rows("SELECT * FROM bullets WHERE id=?", (bullet_id,))[0]
        if bullet["done"] or bullet["note"] or bullet["migrated"] or bullet["day"] == target_day:
            return False
        with self.change():
            self.db.execute("UPDATE bullets SET migrated=1 WHERE id=?", (bullet_id,))
            self.db.execute("INSERT INTO bullets(day,text,chapter_id,habit_id,activity_id,credited) VALUES (?,?,?,?,?,?)",
                            (target_day, bullet["text"], bullet["chapter_id"], bullet["habit_id"], bullet["activity_id"], bullet["credited"]))
        return True

    def delete(self, table, item_id):
        if table not in {"books", "chapters", "habits", "bullets", "paths", "skills"}:
            raise ValueError("Unknown collection")
        with self.change():
            self.db.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))

    def rename(self, table, item_id, title):
        if table not in {"books", "chapters", "habits", "bullets", "paths", "activities", "skills"}:
            raise ValueError("Unknown collection")
        column = "text" if table == "bullets" else "title"
        with self.change():
            self.db.execute(f"UPDATE {table} SET {column}=? WHERE id=?", (title, item_id))
            if table == "books":
                self.db.execute("UPDATE resources SET title=? WHERE book_id=?", (title, item_id))

    def export(self):
        return json.dumps({"version": 2, **{t: self.rows(f"SELECT * FROM {t}") for t in
                          ("books", "chapters", "habits", "checkins", "bullets", *LEARNING_TABLES)}}, indent=2, ensure_ascii=False)

    def seed_demo(self):
        book = self.add_book("Linear Algebra", ["Systems of equations", "Row reduction", "Vector spaces", "Linear independence", "Bases and dimension", "Linear maps", "Eigenvalues", "Inner products"], True)
        self.add_book("A Room of One’s Own", [f"Chapter {n}" for n in range(1, 7)])
        self.add_book("The Craft of Research", ["Thinking in print", "Connecting with your reader", "From topics to questions", "From questions to a problem", "Finding sources"])
        ids = self.rows("SELECT id FROM chapters WHERE book_id=? ORDER BY position", (book,))
        with self.db:
            for chapter in ids[:3]:
                self.db.execute("UPDATE chapters SET reading=2,exercises=1 WHERE id=?", (chapter["id"],))
            self.db.execute("UPDATE chapters SET reading=1 WHERE id=?", (ids[3]["id"],))
        reading = self.add_habit("Read", "sessions", 1, 5)
        exercise = self.add_habit("Exercise", "minutes", 30, 3)
        self.add_habit("Language practice", "minutes", 15, 5)
        today = date.today()
        for n in range(1, 85):
            day = (today - timedelta(days=n)).isoformat()
            if n % 5 != 0:
                self.checkin(reading, day, 1)
            if n % 3 == 0:
                self.checkin(exercise, day, 30)
        self.add_bullet(today.isoformat(), "Read: Linear independence", ids[3]["id"], reading)
        self.add_bullet(today.isoformat(), "Email supervisor")
        self.add_bullet(today.isoformat(), "- Try the exercises before checking solutions")
        self.add_bullet((today - timedelta(days=1)).isoformat(), "Pick up library holds")
        from .demo import DEMO_SYLLABUS
        self.import_syllabus(DEMO_SYLLABUS)
        self._undo.clear()

    def close(self):
        self.db.close()
