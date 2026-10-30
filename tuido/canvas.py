"""TuiDo on a canvas: the desk as one tree you move across (treecanvas, vendored).

Today and its earlier pages, Paths, Library, Habits, Skills, Projects and Ideas branch from the
root, each as deep as it goes: a path's modules and activities, a book's chapters, a project's
steps and subtasks. Pinned focus and the chosen shelf narrow it as they do the desk.

Everything goes through the Store, so each action is one transaction and one undo step:

    Enter   mark it (a task, activity, chapter, step or habit's day), or open it
    ⌃P      plan it into Today      ⌃N  add one here      ⌃E  rename      ⌃D  delete
    ⌃R      continue: to the next activity a path is ready for
    ⌃T      carry an unfinished task forward to today      ⌃Z  undo

    tuido --canvas [--db FILE | --demo]
"""
from datetime import date, timedelta
import json
import os
import threading
import time

from . import treecanvas as tc
from .learning_ui import LEVELS

STATE = {2: ('git_staged', '✓', 'x'), 1: ('git_dirty', '◐', '~')}
SECTIONS = (('today', 'Today'), ('pages', 'Earlier pages'), ('paths', 'Paths'), ('library', 'Library'),
            ('habits', 'Habits'), ('skills', 'Skills'), ('projects', 'Projects'), ('ideas', 'Ideas'))
TABLE = {'path': 'paths', 'activity': 'activities', 'book': 'books', 'chapter': 'chapters', 'habit': 'habits',
         'skill': 'skills', 'project': 'projects', 'task': 'project_tasks', 'idea': 'ideas', 'bullet': 'bullets'}
WEEK = 'MTWTFSS'


def boxes(states, width=8):
    """Progress as boxes, one per part (squeezed to `width`): done ▰, under way ◧, not yet ▱."""
    if not states:
        return ''
    if len(states) > width:
        step = len(states) / width
        states = [states[int(i * step)] for i in range(width)]
    return ''.join('▰' if s == 2 else '◧' if s == 1 else '▱' for s in states)


def ago(day, today):
    days = (today - date.fromisoformat(day)).days
    return 'today' if days == 0 else 'yesterday' if days == 1 else f'{days} days ago'


class Desk(tc.Provider):
    """The provider: nodes carry (kind, row) in data; ids are the way down, /paths/3/a12/a15."""
    pane = True

    def __init__(self, store, path=None, watch=2.0):
        self.store, self.file = store, path
        self.today = date.today
        self.memo = {}          # snapshots, until something changes: a frame asks each node many times
        if path and watch:
            threading.Thread(target=self.watch, args=(watch,), daemon=True).start()

    def watch(self, every):
        """The desk changed by someone else (TuiDo itself, open beside it): show it."""
        def stamp():
            try:
                return tuple(os.stat(p).st_mtime_ns if os.path.exists(p) else 0
                             for p in (self.file, f'{self.file}-wal'))
            except OSError:
                return None
        seen = stamp()
        while True:
            time.sleep(every)
            now = stamp()
            if now != seen:
                seen = now
                self.invalidate()

    def invalidate(self, path=None):
        self.memo.clear()           # anything may have changed: work it all out again
        super().invalidate(path)

    def remember(self, key, work):
        if key not in self.memo:
            self.memo[key] = work()
        return self.memo[key]

    def learning(self, path_id):
        return self.remember(('path', path_id), lambda: self.store.learning_snapshot(path_id))

    def project(self, project_id):
        return self.remember(('project', project_id), lambda: self.store.project_snapshot(project_id, self.today()))

    def unmet(self, path_id, node_id):
        return self.remember(('unmet', path_id, node_id), lambda: self.store.unmet_prerequisites(path_id, node_id))

    # -- the tree
    def root(self):
        return tc.Node('', 'tuido', True, source=self, kind='root')

    def children(self, node):
        s, k = self.store, node.kind
        if k == 'root':
            return [tc.Node('/' + key, name, True, node, key) for key, name in SECTIONS]
        if k in ('today', 'page'):
            day = self.today().isoformat() if k == 'today' else node.data
            return [self.bullet(b, node) for b in s.rows("SELECT * FROM bullets WHERE day=? ORDER BY id", (day,))]
        if k == 'pages':
            days = s.rows("SELECT DISTINCT day FROM bullets WHERE day<? ORDER BY day DESC LIMIT 60",
                          (self.today().isoformat(),))
            return [tc.Node(f'{node.path}/{d["day"]}', self.day_name(d['day']), True, node, 'page', data=d['day'])
                    for d in days]
        if k == 'paths':
            return [self.make(node, 'path', p, f'p{p["id"]}', True) for p in s.sidebar_items('paths')]
        if k in ('path', 'activity'):
            path_id = node.data['path_id'] if k == 'activity' else node.data['id']
            nodes, children, _ = self.learning(path_id)
            under = node.data['id'] if k == 'activity' else None
            return [self.make(node, 'activity', nodes[i], f'a{i}', bool(children.get(i))) for i in children.get(under, [])]
        if k == 'library':
            return [self.make(node, 'book', b, f'b{b["id"]}', True) for b in s.sidebar_items('books')]
        if k == 'book':
            return [self.make(node, 'chapter', c, f'c{c["id"]}', False) for c in
                    s.rows("SELECT * FROM chapters WHERE book_id=? ORDER BY position,id", (node.data['id'],))]
        if k in ('habits', 'habit'):
            items = s.sidebar_items('habits')
            under = node.data['id'] if k == 'habit' else None
            mine = [h for h in items if h['sidebar_parent'] == under]
            return [self.make(node, 'habit', h, f'h{h["id"]}', any(x['sidebar_parent'] == h['id'] for x in items))
                    for h in mine]
        if k == 'skills':
            return [self.make(node, 'skill', sk, f's{sk["id"]}', False) for sk in s.sidebar_items('skills')]
        if k == 'projects':
            return [self.make(node, 'project', p, f'j{p["id"]}', True) for p in s.sidebar_items('projects')]
        if k in ('project', 'task'):
            project = node.data['project_id'] if k == 'task' else node.data['id']
            tasks, children, _ = self.project(project)
            under = node.data['id'] if k == 'task' else None
            return [self.make(node, 'task', tasks[i], f't{i}', bool(children.get(i))) for i in children.get(under, [])]
        if k == 'ideas':
            return [self.make(node, 'idea', i, f'i{i["id"]}', False) for i in s.sidebar_items('ideas')]
        return []

    def make(self, parent, kind, row, key, branch):
        return tc.Node(f'{parent.path}/{key}', row.get('title') or '(untitled)', branch, parent, kind, data=row)

    def bullet(self, b, parent):
        text = ('— ' if b['note'] else '') + b['text']
        return tc.Node(f'{parent.path}/{b["id"]}', text, False, parent, 'bullet', data=b)

    def day_name(self, day):
        d = date.fromisoformat(day)
        return ('yesterday · ' if d == self.today() - timedelta(days=1) else '') + d.strftime('%a %-d %b %Y')

    # -- how it looks
    def state(self, node):
        """2 done, 1 under way, 0 not yet, or None for what has no state."""
        k, d = node.kind, node.data
        if k == 'activity':
            return self.learning(d['path_id'])[2].get(d['id'], 0)
        if k == 'chapter':
            return d['reading']
        if k == 'task':
            return self.project(d['project_id'])[2].get(d['id'], 0)
        if k == 'bullet' and not d['note']:
            return 2 if d['done'] else None
        return None

    def label(self, node):
        k, d = node.kind, node.data
        if k == 'today':
            return f'Today · {self.today().strftime("%a %-d %b")}'
        if k == 'path':
            nodes, children, states = self.learning(d['id'])
            return f'{node.name}  {boxes([states[i] for i in children.get(None, [])])}'
        if k == 'book':
            chapters = self.store.rows("SELECT reading FROM chapters WHERE book_id=? ORDER BY position,id", (d['id'],))
            return f'{node.name}  {boxes([c["reading"] for c in chapters])}'
        if k == 'habit':
            return f'{node.name}  {self.week(d)}'
        if k == 'skill':
            return f'{node.name} · {LEVELS[d["level"]]}'
        if k == 'project':
            _, children, states = self.project(d['id'])
            return f'{node.name}  {boxes([states[i] for i in children.get(None, [])])}'
        if k == 'task' and d['every_days']:
            when = ago(d['last_done'], self.today()) if d['last_done'] else 'not yet'
            return f'{node.name} · every {d["every_days"]} days · {when}'
        if k == 'chapter' and d['exercises']:
            return f'{node.name} · exercises ✓'
        return node.name

    def week(self, habit):
        """This Monday-to-Sunday week, a box a day: met ■, some □, none ·, still to come blank."""
        today = self.today()
        monday = today - timedelta(days=today.weekday())
        counts = self.store.habit_counts(habit['id'], planned=False)
        goal = habit['daily_goal'] if habit['goal_period'] == 'day' else 1
        out = []
        for n in range(7):
            day = monday + timedelta(days=n)
            got = counts.get(day.isoformat(), 0)
            out.append(' ' if day > today else '■' if got >= goal else '□' if got else '·')
        return ''.join(out)

    def mark(self, node):
        if node.kind == 'bullet' and node.data['migrated']:
            return 'stub', '›', '>'
        if node.kind == 'idea' and node.data.get('project_id'):
            return 'git_staged', '↳', '>'
        if node.kind in ('path', 'book', 'habit', 'skill', 'project', 'idea') and node.data.get('pinned'):
            return 'git_staged', '★', '*'
        return STATE.get(self.state(node))

    def dim(self, node):
        k, d = node.kind, node.data
        if k == 'bullet' and (d['done'] or d['migrated']):
            return 0.6
        if k == 'activity' and d['optional']:
            return 0.75
        if k == 'activity' and self.state(node) != 2 and self.unmet(d['path_id'], d['id']):
            return 0.6                      # suggested to wait: it isn't locked, just quieter
        return 1.0

    # -- the pane
    def preview(self, node):
        k, d, s = node.kind, node.data, self.store
        if k == 'root':
            return 'Enter marks or opens · ⌃P plans into Today · ⌃N adds · ⌃R continues · ⌃Z undoes'
        if k in ('today', 'page'):
            day = self.today().isoformat() if k == 'today' else d
            rows = s.rows("SELECT * FROM bullets WHERE day=?", (day,))
            tasks = [b for b in rows if not b['note']]
            return (f'{sum(b["done"] for b in tasks)} of {len(tasks)} done, {len(rows) - len(tasks)} notes\n\n'
                    '⌃N adds to the page; start with "- " for a note.')
        if k == 'bullet':
            linked = self.linked(d)
            return d['text'] + (f'\n\n{linked}' if linked else '') + ('\n\n(carried forward)' if d['migrated'] else '')
        if k == 'path':
            nxt = s.next_activity(d['id'])
            title = s.rows("SELECT title FROM activities WHERE id=?", (nxt,))[0]['title'] if nxt else None
            return (d.get('description') or '') + (f'\n\nNext: {title}  (⌃R)' if title else '\n\nNothing required is ready.')
        if k == 'activity':
            lines = [f'{d["kind"]}' + (' · optional' if d['optional'] else '')]
            if d['resource_uid']:
                res = s.rows("SELECT title, url FROM resources WHERE uid=?", (d['resource_uid'],))
                if res:
                    lines.append('Source: ' + res[0]['title'] + (f'\n{res[0]["url"]}' if res[0]['url'] else ''))
            missing = s.unmet_prerequisites(d['path_id'], d['id'])
            if missing:
                lines.append('Suggested first: ' + ', '.join(missing))
            if d['notes']:
                lines += ['', d['notes']]
            return '\n'.join(lines)
        if k == 'chapter':
            return ('not read', 'reading', 'read')[d['reading']] + (' · exercises done' if d['exercises'] else '')
        if k == 'habit':
            return self.heatmap(d)
        if k == 'skill':
            return f'{LEVELS[d["level"]]}' + (f'\n\nEvidence: {d["evidence"]}' if d['evidence'] else '')
        if k == 'project':
            nxt = s.next_task(d['id'])
            title = s.rows("SELECT title FROM project_tasks WHERE id=?", (nxt,))[0]['title'] if nxt else None
            return (d['notes'] or '') + (f'\n\nNext: {title}' if title else '')
        if k in ('task', 'idea'):
            return d.get('notes') or None
        return None

    def heatmap(self, habit):
        """Twelve weeks, a row a weekday, as the desk's: met ■, some □, none ·."""
        today = self.today()
        start = today - timedelta(days=today.weekday() + 7 * 11)
        counts = self.store.habit_counts(habit['id'], planned=False)
        goal = habit['daily_goal'] if habit['goal_period'] == 'day' else 1
        rows = []
        for wd in range(7):
            cells = []
            for week in range(12):
                day = start + timedelta(days=7 * week + wd)
                got = counts.get(day.isoformat(), 0)
                cells.append(' ' if day > today else '■' if got >= goal else '□' if got else '·')
            rows.append(f'{WEEK[wd]} {" ".join(cells)}')
        goal_text = (f'{habit["daily_goal"]} {habit["unit"]} a day, {habit["weekly_goal"]} days a week'
                     if habit['goal_period'] == 'day' else f'{habit["daily_goal"]} {habit["unit"]} a week')
        return goal_text + '\n\n' + '\n'.join(rows)

    def linked(self, b):
        s = self.store
        for column, sql in (('activity_id', "SELECT title FROM activities WHERE id=?"),
                            ('chapter_id', "SELECT title FROM chapters WHERE id=?"),
                            ('project_task_id', "SELECT title FROM project_tasks WHERE id=?"),
                            ('habit_id', "SELECT title FROM habits WHERE id=?")):
            if b.get(column):
                row = s.rows(sql, (b[column],))
                if row:
                    return f'For: {row[0]["title"]}'
        return ''

    # -- doing
    def choose(self, node):
        """Enter on something with a state marks it; on a branch it opens (the canvas does)."""
        s, k, d = self.store, node.kind, node.data
        try:
            if k == 'bullet':
                s.toggle_bullet(d['id'])
            elif k == 'activity' and not node.is_dir:
                s.cycle_activity(d['id'])
            elif k == 'chapter':
                s.cycle_chapter(d['id'])
            elif k == 'task' and not node.is_dir:
                if s.cycle_task(d['id']) is False:
                    self.status('mark', f'{node.name}: done already, back in {d["every_days"]} days', 'note')
                    return None
            elif k == 'habit':
                s.checkin(d['id'], self.today().isoformat(), 1)
            else:
                return None
        except ValueError as e:
            self.status('mark', str(e), 'failed')
            return None
        self.changed_here(node)
        return None

    def changed_here(self, node):
        """After a change: everything again (one query each), and the node flashes."""
        self.invalidate()
        self.pulse(node.path)

    def actions(self, node):
        k = node.kind
        out = []
        if (k in ('activity', 'task') and not node.is_dir) or k in ('chapter', 'habit'):
            out.append(('\x10', 'plan', '⌃P plan'))
        if k in ('today', 'page', 'paths', 'path', 'activity', 'library', 'book', 'habits', 'projects', 'project',
                 'task', 'ideas', 'bullet'):
            out.append(('\x0e', 'new', '⌃N add'))
        if k in TABLE:
            out += [('\x05', 'rename', '⌃E rename'), ('\x04', 'delete', '⌃D delete')]
        if k in ('path', 'activity'):
            out.append(('\x12', 'continue', '⌃R continue'))
        if k == 'bullet' and not node.data['done'] and not node.data['note'] and not node.data['migrated'] \
                and node.data['day'] != self.today().isoformat():
            out.append(('\x14', 'today', '⌃T to today'))
        return out + [('\x1a', 'undo', '⌃Z undo')]

    def act(self, node, name, canvas):
        s, k, d = self.store, node.kind, node.data
        today = self.today().isoformat()

        def attempt(fn, done=None):
            try:
                fn()
            except ValueError as e:
                canvas.status('act', str(e), 'failed')
                return None
            self.changed_here(node)
            if done:
                canvas.status('act', done, 'ok')
            return None

        def typed(make, done=None):
            """For the typing line: what's typed, if anything, made into something. It returns None
            whatever happens: anything else would close the canvas."""
            return lambda text: attempt(lambda: make(text.strip()), done) if text.strip() else None

        if name == 'undo':
            if s.undo():
                self.invalidate()
                canvas.status('act', 'undone', 'ok')
            else:
                canvas.status('act', 'nothing to undo', 'note')
        elif name == 'plan':
            default = f'Read: {node.name}' if k == 'chapter' else node.name
            ids = dict(activity_id=d['id']) if k == 'activity' else dict(chapter_id=d['id']) if k == 'chapter' \
                else dict(project_task_id=d['id']) if k == 'task' else dict(habit_id=d['id'])
            canvas.ask('plan for today', typed(lambda text: s.add_bullet(today, text, **ids), 'planned into Today'),
                       text=default)
        elif name == 'today':
            attempt(lambda: s.migrate(d['id'], today), 'carried to today')
        elif name == 'rename':
            table = TABLE[k]
            current = d['text'] if k == 'bullet' else d['title']
            canvas.ask('rename', typed(lambda text: s.rename(table, d['id'], text)), text=current)
        elif name == 'delete':
            what = node.name

            def gone(key):
                if key != 'y':
                    return
                if k == 'activity':
                    attempt(lambda: s.archive_activity(d['id']))
                else:
                    attempt(lambda: s.delete(TABLE[k], d['id']))
                canvas.status('act', what, 'gone')
            canvas.ask(f'delete {tc.clip(what, 40)}?  y yes  n no  (⌃Z brings it back)', gone, choices='yn')
        elif name == 'new':
            self.new(node, canvas, typed)
        elif name == 'continue':
            path_id = d['path_id'] if k == 'activity' else d['id']
            nxt = s.next_activity(path_id)
            if not nxt:
                canvas.status('act', 'nothing required is ready: see what is optional, or suggested first', 'note')
                return None
            nodes, _, _ = s.learning_snapshot(path_id)
            chain, at = [], nxt
            while at:
                chain.append(f'a{at}')
                at = nodes[at]['parent_id']
            ids, way = ['/paths', f'/paths/p{path_id}'], f'/paths/p{path_id}'
            for key in reversed(chain):
                way += '/' + key
                ids.append(way)
            if canvas.go(ids):                  # the camera flies there
                self.pulse(ids[-1])
        return None

    def new(self, node, canvas, typed):
        """⌃N: add one where you are: to the page, the path, the book, the project…"""
        s, k, d = self.store, node.kind, node.data
        if k in ('today', 'page', 'bullet'):
            day = (d['day'] if k == 'bullet' else d if k == 'page' else self.today().isoformat())
            canvas.ask('add ("- " for a note)', typed(lambda t: s.add_bullet(day, t.strip())))
        elif k == 'paths':
            canvas.ask('a new path', typed(lambda t: s.add_path(t.strip())))
        elif k in ('path', 'activity'):
            path_id = d['path_id'] if k == 'activity' else d['id']
            parent = d['id'] if k == 'activity' and node.is_dir else d.get('parent_id') if k == 'activity' else None
            canvas.ask('a new activity', typed(lambda t: s.add_activity(path_id, t.strip(), parent_id=parent)))
        elif k == 'library':
            canvas.ask('a new book (its chapters after a |, split by ;)', typed(
                lambda t: s.add_book(t.split('|')[0].strip(), [c.strip() for c in (t.split('|', 1)[1:] or [''])[0].split(';') if c.strip()])))
        elif k == 'book':
            canvas.ask('a new chapter', typed(lambda t: s.add_chapter(d['id'], t.strip())))
        elif k == 'habits':
            canvas.ask('a new habit', typed(lambda t: s.add_habit(t.strip())))
        elif k == 'projects':
            canvas.ask('a new project', typed(lambda t: s.add_project(t.strip())))
        elif k in ('project', 'task'):
            project = d['project_id'] if k == 'task' else d['id']
            parent = d['id'] if k == 'task' and node.is_dir else d.get('parent_id') if k == 'task' else None
            canvas.ask('a new step', typed(lambda t: s.add_task(project, t.strip(), parent)))
        elif k == 'ideas':
            canvas.ask('a new idea', typed(lambda t: s.add_idea(t.strip())))


def run(store, path=None):
    """The canvas, in the terminal, until Esc."""
    tc.pick('', provider=Desk(store, path), glyphs='plain', colmax=40)
