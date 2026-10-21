# TuiDo

Learning paths, a reading library, habit tracking, and a daily bullet journal in
one terminal app. Build a syllabus by hand or give an agent your learning materials
and import the result.

![TuiDo learning paths](docs/screenshots/paths.svg)

## Start

Requires Python 3.11+. With [uv](https://docs.astral.sh/uv/):

```sh
uv run tuido --demo
uv run tuido
```

The demo uses a temporary database and leaves your journal alone. Alternatively:

```sh
python -m pip install -e .
tuido --demo
```

For the virtual environment already in this workspace:

```sh
.venv/bin/python -m tuido --demo
```

## The desk

- **Paths:** syllabi organized around outcomes, with expandable modules, books,
  chapter readings, videos, articles, exercises, and projects. Sidebar boxes show
  progress through the top-level modules. Required children determine completion;
  enrichment can be optional. Continue finds the next unfinished required activity
  whose suggested prerequisites are complete. Prerequisites guide you without
  locking the rest of the path.
- **Library:** standalone books and books referenced by syllabi. Each title has
  progress boxes; chapters appear to its right. Reading has three states, and
  textbook exercises have a separate checkoff. Reference the same resource/chapter
  in multiple paths to share progress. Manually created activities can also link
  to an existing Library chapter.
- **Habits:** seven sidebar boxes for the current Monday–Sunday week and a
  12-week heatmap. Log checkoffs or quantities such as minutes and pages. Partial
  days have their own state; weekly targets count days meeting the daily goal.
- **Skills:** milestones with suggested evidence drawn from syllabus activities.
  Choose Not yet, Explored, Practised, or Demonstrated. Demonstrated requires
  recorded evidence; finishing readings does not automatically claim mastery.
- **Today:** quick tasks and notes in a persistent sidepane. Tomorrow starts a new
  page; older pages remain retrievable. Carry unfinished tasks forward explicitly.
  Plan a syllabus activity or chapter into Today and check it off there to update
  its original progress in the same undoable transaction.

At 110+ columns, the desk has three columns: a list, its contents, and Today.
Below that, Today starts collapsed. Ctrl+T toggles it. Below 75 columns, showing
Today temporarily hides the left list so the contents and journal still fit.
Use a terminal at least 60 columns wide and 24 rows high. No special font is needed.

## Give an agent your materials

Provide your materials, learning goal, and available time along with
[the agent guide](docs/agent-syllabi.md), [the JSON schema](docs/syllabus.schema.json),
and [the example syllabus](examples/learning-to-learn.json).

```sh
# Validate and preview without importing
uv run tuido --import-syllabus syllabus.json

# Apply the reviewed syllabus
uv run tuido --import-syllabus syllabus.json --apply
```

Or use **Paths → Import syllabus** inside the app. Matching stable IDs keep their
progress and skill evidence. Removed activities are archived, preserving journal
history. Failed imports roll back completely. Revisions that change an activity's
meaning need a new ID. See [the format and revision rules](docs/agent-syllabi.md).

```sh
uv run tuido --example my-example.json
uv run tuido --list-paths
uv run tuido --export-syllabus my-path-id --output syllabus.json
```

Syllabus exports contain curriculum structure, not personal progress or skill
evidence, so an agent can revise them without receiving your entire journal.

## Diagrams and ASCII art

Press **v** in Paths to open an in-app, expandable learning map with completion
progress, book sources, prerequisites, and ASCII artwork. Escape returns to your
path. Press **i** to inspect notes and resource links. Attached Mermaid source is
available inside the visual view; export HTML for rendered Mermaid diagrams and
animated web scenes.

```sh
uv run tuido --render-syllabus my-path-id --output syllabus.html
```

Syllabi can attach `mermaid` source, plain `ascii` artwork, and an optional
`ascii_piece` slug from [ASCII Magic](https://www.ascii-magic.com/ascii), such as
`seed-germination`. Mermaid 12.2.0 and selected ASCII Magic scenes load in the
browser; they require internet access. The terminal outline, tracking, plain art,
and exported source remain available offline. Animated scenes respect the ASCII
Magic player's reduced-motion behavior. No Node dependency is required by TuiDo.

## Keys

| Key | Action |
| --- | --- |
| F1 / F2 / F3 / F4 | Paths / Library / Habits / Skills |
| Tab / Shift+Tab | Move between columns and controls |
| Up / Down | Select an item |
| Enter | Expand module / advance activity or chapter / complete task |
| Space | Advance selected activity or chapter / complete task / log habit unit |
| `a` | Add to the focused list |
| `c` | Add a child inside the selected module |
| `n` | Continue the next ready required activity |
| `p` | Plan selected activity or chapter for today |
| `i` / `v` | Inspect notes / open in-app learning map |
| `r` | Edit selected item's text |
| Delete | Delete item, or archive activity; Ctrl+Z restores it |
| `e` | Toggle textbook exercises in Library |
| `+` / `-` | Add / subtract one habit unit today |
| Ctrl+O | Preview and import syllabus JSON |
| Ctrl+J | Jot on the displayed journal date; prefix `- ` for a note |
| Ctrl+T | Show / hide Today |
| Ctrl+Left / Ctrl+Right | Previous / next journal date |
| Ctrl+Y | Carry an unfinished historical task to today |
| Ctrl+Z | Undo up to 50 changes in the current session |
| `?` | Help |
| Ctrl+Q | Quit |

Reopening a linked daily task keeps its recorded progress. Rechecking it does not
log habit credit twice. Use Undo to reverse the entire linked action. Linking a
habit to a planned task logs **one unit** on completion; log time separately for
habits measured in minutes.

## Your data

SQLite storage lives at `$XDG_DATA_HOME/tuido/tuido.sqlite3`, defaulting to
`~/.local/share/tuido/tuido.sqlite3`. Changes commit immediately; existing book,
habit, and journal databases migrate automatically. Undo history is session-only.

```sh
uv run tuido --db ./my-journal.sqlite3
uv run tuido --export ./journal-backup.json
uv run tuido --db ./my-journal.sqlite3 --export ./project-backup.json
```

JSON exports contain all data, including archived activities and personal progress.
Export commands refuse to overwrite existing files. For a restorable backup, copy
the SQLite file while the app is closed. Source control excludes databases and
common backup filenames; keep personal syllabi and exports in `private/`.

Scheduled rest days, automatic extraction of tables of contents, JSON database
restore, and built-in agents are not included. Any agent that can produce the
syllabus format can populate the app; no model API or service is required to use it.

## Development

```sh
uv sync --group dev
uv run pytest -q
```

Tests exercise real keyboard/mouse workflows, layout resizing, shared-resource
progress, syllabus revisions, atomic rollback, existing database migration, skill
evidence, journal history, persistent undo, and CLI preview/import/export behavior.

## Source backup

When `TuiDo.bundle` is present, it is a portable Git backup of the source snapshot,
including tests and documentation. It contains no personal journal database.
Restore it with `git clone ./TuiDo.bundle TuiDo-restored`.

`bash scripts/publish-backup.sh` publishes that snapshot to **3-mmc/TuiDo** using
your authenticated GitHub CLI. It creates a private repository when one does not
exist, and never force-pushes an existing repository. It requires shell network
access; it leaves the cloned snapshot in a temporary directory for inspection.
