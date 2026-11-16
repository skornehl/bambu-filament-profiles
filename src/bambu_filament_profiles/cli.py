"""Command line: ``bfp update | list | install | export | cleanup | app | fetch | build``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .catalog import (
    CATALOG_FORMAT,
    build,
    catalog_age_days,
    list_profiles,
    load_records,
    read_build_info,
    select_profiles,
    update_profiles,
    write_output,
)
from .fetch import FetchError, fetch_all, read_lock, write_lock
from .generate import DEFAULT_PRINTER, ExpandError, expand, filament_id_for
from .matching import alias_of, safe_filename
from .install import (
    InstallError,
    backup,
    bambu_running,
    checklist_markdown,
    choose_installation,
    choose_user,
    default_data_dir,
    delete_local,
    filter_presets,
    find_installations,
    plan_install,
    printers_label,
    scan_user_presets,
    write_profile,
)
from .sources.bambu import BambuProfiles

REPO_ROOT = Path(__file__).resolve().parents[2]
#: From this age (days) on, the tool points to ``bfp update``.
MAX_AGE_DAYS = 30
CLOUD_HINT = (
    "Please delete profiles synced with the cloud in Bambu Studio: "
    "File → Batch Preset Management, tick the profiles, Delete. "
    "If they are only deleted locally, Bambu Studio downloads them again from the cloud on the next start."
)


def main(argv: list[str] | None = None, ask=None, out=print) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if ask is None and sys.stdin.isatty():
        ask = input
    try:
        return args.func(args, ask, out)
    except (InstallError, FetchError, OSError, ValueError) as exc:
        out(f"Error: {exc}")
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bfp", description="Generate and install Bambu Studio filament profiles")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    data = default_data_dir()

    p = sub.add_parser("update", help="fetch the newest sources and rebuild the profiles locally")
    _source_args(p, data)
    p.add_argument("--manual", type=Path, default=REPO_ROOT / "manual")
    p.add_argument("--out", type=Path, default=data / "profiles")
    p.add_argument("--printer", default=DEFAULT_PRINTER)
    p.add_argument("--pinned", action="store_true", help="fetch the commits from the lock file instead of the newest")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("fetch", help="only fetch the source repos (newest state)")
    _source_args(p, data)
    p.add_argument("--pinned", action="store_true", help="fetch the commits from the lock file instead of the newest")
    p.add_argument("--only", action="append", default=[], help="only this source (repeatable)")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("build", help="only build the profiles from the sources fetched before")
    _source_args(p, data)
    p.add_argument("--manual", type=Path, default=REPO_ROOT / "manual")
    p.add_argument("--out", type=Path, default=data / "profiles")
    p.add_argument("--printer", default=DEFAULT_PRINTER)
    p.set_defaults(func=cmd_build)

    for name, helptext in (
        ("list", "show the generated profiles"),
        ("install", "install profiles into Bambu Studio"),
        ("export", "write standalone profiles into a folder for importing by hand"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--profiles", type=Path, default=data / "profiles")
        p.add_argument("--vendor", action="append", default=[], help="brand (substring, repeatable)")
        p.add_argument("--material", action="append", default=[], help="material, e.g. PLA (repeatable)")
        p.add_argument("--name", action="append", default=[], help="product (substring, repeatable)")
        if name == "install":
            _target_args(p)
            p.add_argument("--all", action="store_true", help="install all profiles without a filter")
            p.add_argument("--overwrite", action="store_true", help="overwrite existing profiles with the same name without asking")
            p.set_defaults(func=cmd_install)
        elif name == "export":
            p.add_argument("--out", type=Path, required=True, help="target folder")
            p.add_argument("--data-dir", help="Bambu Studio data folder (found automatically otherwise)")
            p.add_argument("--cache", type=Path, default=data / "sources", help="fallback: source cache")
            p.set_defaults(func=cmd_export)
        else:
            p.set_defaults(func=cmd_list)

    p = sub.add_parser("app", help="open the companion app in the browser: search, install, clean up")
    p.add_argument("--profiles", type=Path, default=data / "profiles")
    p.add_argument("--data-dir", help="Bambu Studio data folder (found automatically otherwise)")
    p.add_argument("--backup-dir", type=Path, default=data / "backups")
    p.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (taken → a free port)")
    p.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    p.set_defaults(func=cmd_app)

    p = sub.add_parser("cleanup", help="list and clean up your existing filament profiles")
    _target_args(p)
    p.add_argument("--vendor", action="append", default=[], help="brand or part of the name (repeatable)")
    p.add_argument("--name", action="append", default=[], help="part of the name (repeatable)")
    p.add_argument("--generic", action="store_true", help='only profiles Bambu Studio files under "Generic"')
    p.add_argument("--from-tool", action="store_true", help="only profiles installed by this tool")
    p.add_argument("--not-for", metavar="PRINTER", help='only profiles that do not apply to this printer, e.g. "P1S 0.4"')
    p.add_argument("--delete-local", action="store_true", help="delete local (not synced) profiles only")
    p.add_argument("--list-file", type=Path, help="write the list of profiles to delete as Markdown")
    p.set_defaults(func=cmd_cleanup)
    return parser


def _source_args(p: argparse.ArgumentParser, data: Path) -> None:
    p.add_argument("--cache", type=Path, default=data / "sources", help="folder for the source repos")
    p.add_argument("--lock", type=Path, default=data / "sources.lock.json", help="fetched source commits")


def _target_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--data-dir", help="Bambu Studio data folder (found automatically otherwise)")
    p.add_argument("--user", help='user folder (Bambu account ID or "default")')
    p.add_argument("--backup-dir", type=Path, default=default_data_dir() / "backups")
    p.add_argument("--dry-run", action="store_true", help="only show, write nothing")
    p.add_argument("--yes", action="store_true", help="run without asking")
    p.add_argument("--force", action="store_true", help="even if Bambu Studio is running")


# --------------------------------------------------------------------- commands


def _update(profiles: Path, out) -> None:
    """Fetch the sources and rebuild the profiles, using the default places in the data folder."""
    data = default_data_dir()
    result = update_profiles(data / "sources", data / "sources.lock.json", REPO_ROOT / "manual", profiles, DEFAULT_PRINTER, log=out)
    out(f"{len(result.ok)} profiles written to {profiles}")


def _catalog(args, out) -> list[dict]:
    """The generated profiles; if they are missing in the default place, fetch and build them first."""
    items = list_profiles(args.profiles)
    info = read_build_info(args.profiles)
    outdated = bool(items) and (info or {}).get("format", 1) < CATALOG_FORMAT
    if not items or outdated:
        if Path(args.profiles) != default_data_dir() / "profiles":
            if outdated:
                out(f'Note: the profiles were built by an older version. "bfp update --out {args.profiles}" rebuilds them.')
                return items
            raise InstallError(f"No profiles in {args.profiles}. Build them first: bfp update --out {args.profiles}")
        if outdated:
            out("The profiles were built by an older version: rebuilding them (takes a moment) …")
        else:
            out("No profiles on this computer yet: fetching the sources and building the profiles (once, takes a moment) …")
        _update(args.profiles, out)
        return list_profiles(args.profiles)
    age = catalog_age_days(info)
    if age > MAX_AGE_DAYS:
        out(f'Note: the profiles are {age} days old. "bfp update" fetches the newest state.')
    return items


def cmd_update(args, ask, out) -> int:
    result = update_profiles(args.cache, args.lock, args.manual, args.out, args.printer, pinned=args.pinned, log=out)
    out(f"{len(result.ok)} profiles written to {args.out}; details in {args.out / 'REPORT.md'}")
    return 0


def cmd_fetch(args, ask, out) -> int:
    lock = read_lock(args.lock)
    new_lock = fetch_all(args.cache, lock, update=not args.pinned, names=set(args.only) or None, log=out)
    if new_lock != lock:
        write_lock(args.lock, new_lock)
        out(f"Lock file updated: {args.lock}")
    return 0


def cmd_build(args, ask, out) -> int:
    lock = read_lock(args.lock)
    bambu = BambuProfiles(args.cache / "bambu")
    records = load_records(args.cache, args.manual, args.printer, log=out)
    result = build(records, bambu, args.printer)
    write_output(result, args.out, lock, args.printer)
    out(f"{len(result.ok)} profiles written to {args.out}; details in {args.out / 'REPORT.md'}")
    return 0


def cmd_list(args, ask, out) -> int:
    items = select_profiles(_catalog(args, out), args.vendor, args.material, args.name)
    for item in items:
        out(f"{item['brand']} / {item['material']} / {item['product']}")
    out(f"{len(items)} profiles")
    return 0


def cmd_app(args, ask, out) -> int:
    from .appmodel import AppSession
    from .webapp import run_app

    _catalog(args, out)
    session = AppSession(args.profiles, args.backup_dir, data_dir=args.data_dir, updater=lambda log: _update(args.profiles, log))
    return run_app(session, port=args.port, open_browser=not args.no_browser, out=out)


def cmd_export(args, ask, out) -> int:
    items = select_profiles(_catalog(args, out), args.vendor, args.material, args.name)
    if not items:
        out("No matching profiles found")
        return 1
    found = [] if args.data_dir else find_installations()
    if args.data_dir or found:
        data_dir = Path(args.data_dir).expanduser() if args.data_dir else found[0].data_dir
        system = BambuProfiles.from_installation(data_dir)
        out(f"Base profiles from {data_dir} (version {system.bundle_version or '?'})")
    else:
        system = BambuProfiles(args.cache / "bambu")
        out(f"Base profiles from the source cache {args.cache / 'bambu'}")
    args.out.mkdir(parents=True, exist_ok=True)
    written = 0
    for item in items:
        spec = json.loads(item["path"].read_text(encoding="utf-8"))
        try:
            data = expand(spec, system, filament_id_for(alias_of(spec["name"])))
        except ExpandError as exc:
            out(f"  [ERROR] {spec['name']}: {exc.args[0]}")
            continue
        (args.out / f"{safe_filename(spec['name'])}.json").write_text(json.dumps(data, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
        written += 1
    out(f"{written} profiles written to {args.out}. In Bambu Studio: File → Import → Import Configs.")
    return 0


def _target(args, ask, out, writes: bool = True):
    inst = choose_installation(find_installations(), args.data_dir, ask)
    user = choose_user(inst.data_dir, args.user, ask)
    filament_dir = inst.data_dir / "user" / user / "filament"
    out(f"Bambu Studio: {inst}")
    out(f"User folder: {user}{' (not logged in)' if user == 'default' else ''}")
    if writes and bambu_running():
        out("Warning: Bambu Studio is running. Please close it, otherwise it only sees the changes after a restart")
        out("and may overwrite them when it exits.")
        if not args.dry_run and not args.force:
            raise InstallError("aborted because Bambu Studio is running (use --force to run anyway)")
    return inst, user, filament_dir


def _confirm(args, ask, question: str) -> bool:
    if args.yes:
        return True
    if ask is None:
        raise InstallError("cannot ask; confirm with --yes")
    return ask(f"{question} [y/N] ").strip().lower() in {"y", "yes", "j", "ja"}


def cmd_install(args, ask, out) -> int:
    if not (args.vendor or args.material or args.name or args.all):
        raise InstallError("please select with --vendor, --material or --name (or --all for everything)")
    items = select_profiles(_catalog(args, out), args.vendor, args.material, args.name)
    if not items:
        out("No matching profiles found")
        return 1
    inst, user, filament_dir = _target(args, ask, out)
    try:
        system = BambuProfiles.from_installation(inst.data_dir)
    except FileNotFoundError as exc:
        raise InstallError(f"system profiles of the installation not found ({exc}); start Bambu Studio once") from exc
    out(f"System profiles of the installation: version {system.bundle_version or '?'}")
    existing, problems = scan_user_presets(filament_dir)
    for problem in problems:
        out(f"Note: {problem}")
    actions, errors = plan_install([i["path"] for i in items], filament_dir, existing, system, user)
    for error in errors:
        out(f"  [ERROR] {error}")
    for action in actions:
        label = {"new": "new", "same": "unchanged", "conflict": "EXISTS"}[action.kind]
        out(f"  [{label}] {action.name}")
    new = [a for a in actions if a.kind == "new"]
    conflicts = [a for a in actions if a.kind == "conflict"]
    out(f"{len(new)} new, {len(conflicts)} already present with different content, {len(actions) - len(new) - len(conflicts)} unchanged")
    if args.dry_run:
        out("Dry run: nothing written")
        return 0
    chosen = list(new)
    for action in conflicts:
        if args.overwrite or (ask is not None and not args.yes and _confirm(args, ask, f'Overwrite "{action.name}"?')):
            chosen.append(action)
        else:
            out(f"skipped: {action.name}")
    if not chosen:
        out("Nothing to do")
        return 0
    if not _confirm(args, ask, f"Write {len(chosen)} profiles to {filament_dir / 'base'}?"):
        out("Cancelled")
        return 1
    archive = backup(filament_dir, args.backup_dir, user)
    out(f"Backup: {archive}")
    for action in chosen:
        write_profile(action, user)
    out(f"{len(chosen)} profiles installed. Restart Bambu Studio; when logged in it uploads them to the cloud.")
    return 0


def cmd_cleanup(args, ask, out) -> int:
    inst, user, filament_dir = _target(args, ask, out, writes=args.delete_local)
    presets, problems = scan_user_presets(filament_dir)
    for problem in problems:
        out(f"Note: {problem}")
    try:
        system = BambuProfiles.from_installation(inst.data_dir)
    except FileNotFoundError:
        system = None
    selected = filter_presets(presets, args.vendor, args.name, args.generic, args.from_tool, args.not_for, system)
    out(f"{len(selected)} of {len(presets)} own filament profiles selected:")
    for p in selected:
        cloud = "cloud" if p.synced else "local"
        out(f"  [{cloud}] {p.name} — {p.kind}, brand: {p.shown_vendor}, printers: {_printers(p, system)}")
    synced = [p for p in selected if p.synced]
    local = [p for p in selected if not p.synced]
    if args.list_file:
        args.list_file.write_text(_cleanup_list(selected, user), encoding="utf-8")
        out(f"List written: {args.list_file}")
    if synced:
        out(f"{len(synced)} of them are synced with the cloud. {CLOUD_HINT}")
    if not args.delete_local:
        out("Add --delete-local to delete the local profiles")
        return 0
    if not local:
        out("No local profiles to delete")
        return 0
    if args.dry_run:
        out(f"Dry run: {len(local)} local profiles would be deleted")
        return 0
    if not _confirm(args, ask, f"Delete {len(local)} local profiles?"):
        out("Cancelled")
        return 1
    archive = backup(filament_dir, args.backup_dir, user)
    out(f"Backup: {archive}")
    for preset in local:
        delete_local(preset)
    out(f"{len(local)} local profiles deleted")
    return 0


_printers = printers_label
_cleanup_list = checklist_markdown


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
