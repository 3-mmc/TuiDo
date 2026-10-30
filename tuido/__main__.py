import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from .store import Store
from .syllabus import SyllabusError, load_syllabus


def twigs_canvas():
    """twigs' tasks canvas (github.com/3-mmc/twigs), where twigs is: importable here, or found by
    its `twigs` command; None if it's nowhere."""
    import shutil, sys
    try:
        from twigs.apps.tasks.canvas import run
        return run
    except ImportError:
        pass
    found = shutil.which("twigs")
    if not found:
        return None
    sys.path.insert(0, os.path.dirname(os.path.realpath(found)))
    try:
        from twigs.apps.tasks.canvas import run
        return run
    except ImportError:
        return None


def main():
    parser = argparse.ArgumentParser(description="TuiDo — learning paths, habits, and a fresh page each day")
    database = parser.add_mutually_exclusive_group()
    database.add_argument("--demo", action="store_true", help="Try sample data in a temporary database")
    database.add_argument("--db", type=Path, help="Use a particular SQLite database")
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--export", type=Path, metavar="FILE", help="Export all data to JSON and exit")
    operation.add_argument("--import-syllabus", type=Path, metavar="FILE", help="Validate and preview an agent's syllabus")
    operation.add_argument("--export-syllabus", metavar="PATH_ID", help="Export an editable syllabus by stable ID or number")
    operation.add_argument("--render-syllabus", metavar="PATH_ID", help="Export a syllabus with Mermaid previews as HTML")
    operation.add_argument("--list-paths", action="store_true", help="List path IDs and titles")
    operation.add_argument("--example", type=Path, metavar="FILE", help="Write an example syllabus without opening a database")
    parser.add_argument("--apply", action="store_true", help="Apply --import-syllabus after reviewing its preview")
    parser.add_argument("--canvas", action="store_true", help="Open the desk as one tree you move across, on a canvas")
    parser.add_argument("--output", type=Path, metavar="FILE", help="Output for --export-syllabus or --render-syllabus")
    args = parser.parse_args()
    if args.apply and not args.import_syllabus:
        parser.error("--apply requires --import-syllabus")
    if bool(args.output) != bool(args.export_syllabus or args.render_syllabus):
        parser.error("--output is required only with --export-syllabus or --render-syllabus")

    def write(path, text):
        with path.open("x", encoding="utf-8") as output:
            output.write(text + "\n")
        print(f"Wrote {path}")

    try:
        if args.example:
            from .demo import DEMO_SYLLABUS
            write(args.example, json.dumps(DEMO_SYLLABUS, ensure_ascii=False, indent=2))
            return
        syllabus = load_syllabus(args.import_syllabus) if args.import_syllabus else None
        default = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "tuido" / "tuido.sqlite3"
        with TemporaryDirectory(prefix="tuido-demo-") as temporary:
            db_path = Path(temporary) / "demo.sqlite3" if args.demo else args.db or default
            preview_only = syllabus is not None and not args.apply
            store = Store(":memory:" if preview_only and not db_path.exists() else db_path)
            try:
                if args.demo:
                    store.seed_demo()
                if syllabus is not None:
                    summary = store.import_preview(syllabus)
                    print(json.dumps(summary, indent=2, ensure_ascii=False))
                    if args.apply:
                        path_id = store.import_syllabus(syllabus)
                        print(f"Imported path {path_id}. Existing progress and evidence were preserved.")
                    else:
                        print("Preview only. Run again with --apply to import.")
                elif args.export:
                    write(args.export, store.export())
                elif args.list_paths:
                    for path in store.rows("SELECT id,uid,title FROM paths ORDER BY id"):
                        print(f'{path["id"]}\t{path["uid"]}\t{path["title"]}')
                elif args.export_syllabus or args.render_syllabus:
                    target = args.export_syllabus or args.render_syllabus
                    paths = store.rows("SELECT id FROM paths WHERE uid=?", (target,))
                    if not paths and target.isdecimal():
                        paths = store.rows("SELECT id FROM paths WHERE id=?", (int(target),))
                    if not paths:
                        raise SyllabusError(f"Unknown learning path: {target}. Use --list-paths.")
                    if args.export_syllabus:
                        write(args.output, json.dumps(store.export_syllabus(paths[0]["id"]), indent=2, ensure_ascii=False))
                    else:
                        from .visuals import render_path_html
                        write(args.output, render_path_html(store, paths[0]["id"]))
                elif args.canvas:
                    canvas = twigs_canvas()
                    if canvas is None:
                        parser.exit(2, "tuido: the canvas is a twig now: install twigs (github.com/3-mmc/twigs), "
                                       "then `twigs install tasks`\n")
                    canvas(store, None if args.demo else db_path)    # watched for changes made beside it
                else:
                    from .app import Tuido
                    Tuido(store, demo=args.demo).run()
            finally:
                store.close()
    except (OSError, SyllabusError) as exc:
        parser.exit(2, f"tuido: {exc}\n")


if __name__ == "__main__":
    main()
