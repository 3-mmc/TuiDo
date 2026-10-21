# Give an agent your materials

Give the agent this file, [the schema](syllabus.schema.json), the
[example](../examples/learning-to-learn.json), and your list of materials.
No agent or API subscription is required by TuiDo itself.

A useful prompt:

> Build a TuiDo syllabus from the materials below. My goal is [goal], my starting
> point is [background], and I can study [time] per week. Follow
> docs/syllabus.schema.json and examples/learning-to-learn.json. Organize modules
> around learning outcomes, nest readings, videos, exercises, and projects inside
> them, and include a few skills with evidence criteria. Mark enrichment optional.
> Verify the links and chapter titles you can access; flag unavailable information
> in notes instead of inventing it. Leave missing URLs empty. Preserve all stable
> IDs when revising an existing syllabus. Do not set completion or skill levels.
> Write the result to syllabus.json and validate it with TuiDo's preview command.
>
> Materials: [paste your list here]

```sh
uv run tuido --import-syllabus syllabus.json
uv run tuido --import-syllabus syllabus.json --apply
```

The first command validates and previews. The second applies one transaction.
Inside the app, use **Paths → Import syllabus** (Ctrl+O) to preview and import.
A failed import rolls back completely. An import made inside the app can be undone
with Ctrl+Z; command-line imports persist after the process exits.

## Format and identity

A syllabus has `version: 1`, a stable `id`, a `title`, and a list of `modules`.
The top-level modules are the boxes shown in the Paths sidebar. `description`,
`resources`, `skills`, `mermaid`, `ascii`, and `ascii_piece` are optional.

Every module/activity has its own `id` and `title`. It can contain `children`.
Kinds are `module`, `read`, `video`, `article`, `exercise`, `project`, and `note`.
An explicit kind is recommended. Without one, an activity with children is a
module, and a leaf is a reading activity. `notes` holds instructions or unresolved
questions. `requires` lists activity IDs in the same syllabus; these are advisory
prerequisites, not locks. **Continue** respects them, including a parent module's
prerequisites. `optional: true` excludes enrichment from a parent's required
completion. If a container has only optional children, its boxes reflect those
children instead of reporting completion before anything is done.

Resource IDs are global across syllabi: use an edition-specific ISBN, canonical
URL-derived identifier, or another stable namespaced ID. Activity and skill IDs
are local to a syllabus. Use letters, numbers, periods, underscores, colons,
slashes, and hyphens. Keep IDs under 160 characters. A resource has a title, a type
(`book`, `video`, `article`, `course`, `other`), and an optional HTTP(S) URL. Books
can contain `chapters` with stable IDs and titles, plus `textbook: true`.

An activity references a resource with `resource: "resource-id"` and optionally a
chapter with `chapter: "chapter-id"`. Full books can be nested like this:

```json
{
  "id": "read-the-book",
  "title": "Read the assigned book",
  "kind": "read",
  "children": [
    {"id": "read-intro", "title": "Read the introduction", "kind": "read",
     "resource": "isbn:example-edition", "chapter": "introduction"},
    {"id": "solve-intro", "title": "Solve the introduction exercises", "kind": "exercise",
     "resource": "isbn:example-edition", "chapter": "introduction"}
  ]
}
```

Declare that resource and chapter in the syllabus's `resources` list. A read
reference shares chapter reading progress with the Library and other syllabi.
An exercise reference to the same chapter shares its separate exercise checkoff.
A project or an independent exercise keeps its own activity progress. Videos and
articles linked to the same resource share their consumption progress. A book
reference with no chapter children reflects all of its Library chapters; track
those chapters in the Library or explicitly include chapter children in the tree.

Resource URLs are stored and displayed; TuiDo never fetches them or executes
syllabus instructions. Imported code is never executed. Inputs are limited to
2 MB, 2,000 activities, and 12 nesting levels; duplicate IDs, missing references,
control characters, and prerequisite cycles are rejected.

## Revisions

Export before asking an agent to revise an existing path:

```sh
uv run tuido --list-paths
uv run tuido --export-syllabus my-path-id --output syllabus.json
```

Reimporting the same path and activity IDs updates text, ordering, prerequisites,
and structure while retaining progress. Removed activities and skills are archived;
existing journal links and evidence remain intact. Reintroducing their IDs restores
them. Removed resource chapters remain in the Library to preserve shared progress.
A resource cannot change type under an existing ID. An activity cannot change kind
or its resource/chapter reference under an existing ID: assign a fresh ID when the
meaning changes. Skill assessments and evidence are never imported or reset.

Syllabus exports contain the editable curriculum, not personal completion or
skill evidence. `--export backup.json` exports all stored data, including archived
records and personal progress; keep that file private. For a restorable backup,
copy the SQLite file while the app is closed.

## Visuals and skills

`mermaid` holds diagram source on either the syllabus or an activity. Press `v`
in Paths to open a local HTML preview containing the syllabus, an automatically
generated dependency map, and attached diagrams. Or export it explicitly:

```sh
uv run tuido --render-syllabus my-path-id --output syllabus.html
```

Mermaid 12.2.0 loads from jsDelivr in the browser in strict mode. Source text and
plain artwork remain available offline. Diagram syntax is interpreted by Mermaid
when the preview opens; the importer only validates that the source is text.

`ascii` holds plain artwork shown in the details pane and HTML preview. Optional
`ascii_piece` selects a scene from [ASCII Magic](https://www.ascii-magic.com/ascii),
for example `seed-germination`. Its web component loads from ASCII Magic when the
preview opens; no Node runtime or JavaScript is needed inside the TUI. The library
supports reduced motion. External renderers require internet access. An invalid
or unavailable piece does not affect the stored syllabus or terminal tracking.
See the [ASCII Magic docs](https://www.ascii-magic.com/ascii/docs).

Each skill has an ID, title, and optional `criteria` listing activity IDs as
suggested evidence. The Skills view shows their completion, but you choose the
assessment: **Not yet → Explored → Practised → Demonstrated**. Demonstrated requires
you to record evidence. Course completion never automatically claims mastery.
