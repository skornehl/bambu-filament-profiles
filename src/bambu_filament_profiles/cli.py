"""Kommandozeile: ``bfp fetch | build | list | install | cleanup``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .catalog import build, list_profiles, load_records, select_profiles, write_output
from .fetch import fetch_all, read_lock, write_lock
from .generate import DEFAULT_PRINTER, ExpandError, expand, filament_id_for
from .matching import alias_of, safe_filename
from .install import (
    InstallError,
    backup,
    bambu_running,
    choose_installation,
    choose_user,
    default_data_dir,
    delete_local,
    filter_presets,
    find_installations,
    plan_install,
    scan_user_presets,
    write_profile,
)
from .sources.bambu import BambuProfiles

REPO_ROOT = Path(__file__).resolve().parents[2]
CLOUD_HINT = (
    "Mit der Cloud synchronisierte Profile bitte in Bambu Studio löschen: "
    "Datei → Verwaltung von Batch-Profilen (engl. Batch Preset Management), Profile anhaken, Löschen. "
    "Nur lokal gelöscht lädt Bambu Studio sie beim nächsten Start wieder aus der Cloud."
)


def main(argv: list[str] | None = None, ask=None, out=print) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if ask is None and sys.stdin.isatty():
        ask = input
    try:
        return args.func(args, ask, out)
    except (InstallError, OSError, ValueError) as exc:
        out(f"Fehler: {exc}")
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bfp", description="Bambu-Studio-Filamentprofile erzeugen und installieren")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("fetch", help="Quell-Repos in den Cache holen (Stände aus sources.lock.json)")
    p.add_argument("--cache", type=Path, default=default_data_dir() / "sources")
    p.add_argument("--lock", type=Path, default=REPO_ROOT / "sources.lock.json")
    p.add_argument("--update", action="store_true", help="neueste Stände holen und Lock-Datei aktualisieren")
    p.add_argument("--only", action="append", default=[], help="nur diese Quelle (mehrfach möglich)")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("build", help="Profile aus dem Cache erzeugen und unter profiles/ ablegen")
    p.add_argument("--cache", type=Path, default=default_data_dir() / "sources")
    p.add_argument("--lock", type=Path, default=REPO_ROOT / "sources.lock.json")
    p.add_argument("--manual", type=Path, default=REPO_ROOT / "manual")
    p.add_argument("--out", type=Path, default=REPO_ROOT / "profiles")
    p.add_argument("--printer", default=DEFAULT_PRINTER)
    p.set_defaults(func=cmd_build)

    for name, helptext in (
        ("list", "abgelegte Profile anzeigen"),
        ("install", "Profile in Bambu Studio installieren"),
        ("export", "eigenständige Profile zum Importieren von Hand in einen Ordner schreiben"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--profiles", type=Path, default=REPO_ROOT / "profiles")
        p.add_argument("--vendor", action="append", default=[], help="Hersteller (Teilstring, mehrfach möglich)")
        p.add_argument("--material", action="append", default=[], help="Material, z. B. PLA (mehrfach möglich)")
        p.add_argument("--name", action="append", default=[], help="Sorte (Teilstring, mehrfach möglich)")
        if name == "install":
            _target_args(p)
            p.add_argument("--all", action="store_true", help="ohne Filter alle Profile installieren")
            p.add_argument("--overwrite", action="store_true", help="vorhandene gleichnamige Profile ohne Rückfrage überschreiben")
            p.set_defaults(func=cmd_install)
        elif name == "export":
            p.add_argument("--out", type=Path, required=True, help="Zielordner")
            p.add_argument("--data-dir", help="Bambu-Studio-Datenordner (sonst automatisch gesucht)")
            p.add_argument("--cache", type=Path, default=default_data_dir() / "sources", help="Fallback: Quellen-Cache")
            p.set_defaults(func=cmd_export)
        else:
            p.set_defaults(func=cmd_list)

    p = sub.add_parser("cleanup", help="vorhandene eigene Filamentprofile auflisten und aufräumen")
    _target_args(p)
    p.add_argument("--vendor", action="append", default=[], help="Hersteller oder Namensteil (mehrfach möglich)")
    p.add_argument("--name", action="append", default=[], help="Namensteil (mehrfach möglich)")
    p.add_argument("--generic", action="store_true", help="nur Profile, die Bambu Studio unter „Generic“ führt")
    p.add_argument("--from-tool", action="store_true", help="nur Profile, die dieses Tool installiert hat")
    p.add_argument("--not-for", metavar="DRUCKER", help="nur Profile, die nicht für diesen Drucker gelten, z. B. „P1S 0.4“")
    p.add_argument("--delete-local", action="store_true", help="nur lokale (nicht synchronisierte) Profile löschen")
    p.add_argument("--list-file", type=Path, help="Liste der zu löschenden Profile als Markdown schreiben")
    p.set_defaults(func=cmd_cleanup)
    return parser


def _target_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--data-dir", help="Bambu-Studio-Datenordner (sonst automatisch gesucht)")
    p.add_argument("--user", help="Benutzerordner (Bambu-Konto-ID oder „default“)")
    p.add_argument("--backup-dir", type=Path, default=default_data_dir() / "backups")
    p.add_argument("--dry-run", action="store_true", help="nur anzeigen, nichts schreiben")
    p.add_argument("--yes", action="store_true", help="ohne Rückfrage ausführen")
    p.add_argument("--force", action="store_true", help="auch wenn Bambu Studio läuft")


# ----------------------------------------------------------------------- Befehle


def cmd_fetch(args, ask, out) -> int:
    lock = read_lock(args.lock)
    new_lock = fetch_all(args.cache, lock, update=args.update, names=set(args.only) or None, log=out)
    if new_lock != lock:
        write_lock(args.lock, new_lock)
        out(f"Lock-Datei aktualisiert: {args.lock}")
    return 0


def cmd_build(args, ask, out) -> int:
    lock = read_lock(args.lock)
    bambu = BambuProfiles(args.cache / "bambu")
    records = load_records(args.cache, args.manual, args.printer, log=out)
    result = build(records, bambu, args.printer)
    write_output(result, args.out, lock, args.printer)
    out(f"{len(result.ok)} Profile unter {args.out} abgelegt; Details in {args.out / 'REPORT.md'}")
    return 0


def cmd_list(args, ask, out) -> int:
    items = select_profiles(list_profiles(args.profiles), args.vendor, args.material, args.name)
    for item in items:
        out(f"{item['brand']} / {item['material']} / {item['product']}")
    out(f"{len(items)} Profile")
    return 0


def cmd_export(args, ask, out) -> int:
    items = select_profiles(list_profiles(args.profiles), args.vendor, args.material, args.name)
    if not items:
        out("Keine passenden Profile gefunden")
        return 1
    found = [] if args.data_dir else find_installations()
    if args.data_dir or found:
        data_dir = Path(args.data_dir).expanduser() if args.data_dir else found[0].data_dir
        system = BambuProfiles.from_installation(data_dir)
        out(f"Basisprofile aus {data_dir} (Version {system.bundle_version or '?'})")
    else:
        system = BambuProfiles(args.cache / "bambu")
        out(f"Basisprofile aus dem Quellen-Cache {args.cache / 'bambu'}")
    args.out.mkdir(parents=True, exist_ok=True)
    written = 0
    for item in items:
        spec = json.loads(item["path"].read_text(encoding="utf-8"))
        try:
            data = expand(spec, system, filament_id_for(alias_of(spec["name"])))
        except ExpandError as exc:
            out(f"  [FEHLER] {spec['name']}: {exc.args[0]}")
            continue
        (args.out / f"{safe_filename(spec['name'])}.json").write_text(json.dumps(data, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
        written += 1
    out(f"{written} Profile nach {args.out} geschrieben. In Bambu Studio: Datei → Importieren → Konfigurationen importieren.")
    return 0


def _target(args, ask, out, writes: bool = True):
    inst = choose_installation(find_installations(), args.data_dir, ask)
    user = choose_user(inst.data_dir, args.user, ask)
    filament_dir = inst.data_dir / "user" / user / "filament"
    out(f"Bambu Studio: {inst}")
    out(f"Benutzerordner: {user}{' (nicht angemeldet)' if user == 'default' else ''}")
    if writes and bambu_running():
        out("Achtung: Bambu Studio läuft gerade. Bitte schließen, sonst sieht es die Änderungen erst nach einem Neustart")
        out("und kann sie beim Beenden überschreiben.")
        if not args.dry_run and not args.force:
            raise InstallError("Abbruch, weil Bambu Studio läuft (mit --force trotzdem ausführen)")
    return inst, user, filament_dir


def _confirm(args, ask, question: str) -> bool:
    if args.yes:
        return True
    if ask is None:
        raise InstallError("Keine Rückfrage möglich; mit --yes bestätigen")
    return ask(f"{question} [j/N] ").strip().lower() in {"j", "ja", "y", "yes"}


def cmd_install(args, ask, out) -> int:
    items = select_profiles(list_profiles(args.profiles), args.vendor, args.material, args.name)
    if not (args.vendor or args.material or args.name or args.all):
        raise InstallError("Bitte mit --vendor, --material oder --name auswählen (oder --all für alle)")
    if not items:
        out("Keine passenden Profile gefunden")
        return 1
    inst, user, filament_dir = _target(args, ask, out)
    try:
        system = BambuProfiles.from_installation(inst.data_dir)
    except FileNotFoundError as exc:
        raise InstallError(f"Systemprofile der Installation nicht gefunden ({exc}); Bambu Studio einmal starten") from exc
    out(f"Systemprofile der Installation: Version {system.bundle_version or '?'}")
    existing, problems = scan_user_presets(filament_dir)
    for problem in problems:
        out(f"Hinweis: {problem}")
    actions, errors = plan_install([i["path"] for i in items], filament_dir, existing, system, user)
    for error in errors:
        out(f"  [FEHLER] {error}")
    for action in actions:
        label = {"new": "neu", "same": "unverändert", "conflict": "VORHANDEN"}[action.kind]
        out(f"  [{label}] {action.name}")
    new = [a for a in actions if a.kind == "new"]
    conflicts = [a for a in actions if a.kind == "conflict"]
    out(f"{len(new)} neu, {len(conflicts)} schon vorhanden mit anderem Inhalt, {len(actions) - len(new) - len(conflicts)} unverändert")
    if args.dry_run:
        out("Probelauf: nichts geschrieben")
        return 0
    chosen = list(new)
    for action in conflicts:
        if args.overwrite or (ask is not None and not args.yes and _confirm(args, ask, f"„{action.name}“ überschreiben?")):
            chosen.append(action)
        else:
            out(f"übersprungen: {action.name}")
    if not chosen:
        out("Nichts zu tun")
        return 0
    if not _confirm(args, ask, f"{len(chosen)} Profile nach {filament_dir / 'base'} schreiben?"):
        out("Abgebrochen")
        return 1
    archive = backup(filament_dir, args.backup_dir, user)
    out(f"Backup: {archive}")
    for action in chosen:
        write_profile(action, user)
    out(f"{len(chosen)} Profile installiert. Bambu Studio neu starten; angemeldet lädt es sie in die Cloud hoch.")
    return 0


def cmd_cleanup(args, ask, out) -> int:
    inst, user, filament_dir = _target(args, ask, out, writes=args.delete_local)
    presets, problems = scan_user_presets(filament_dir)
    for problem in problems:
        out(f"Hinweis: {problem}")
    try:
        system = BambuProfiles.from_installation(inst.data_dir)
    except FileNotFoundError:
        system = None
    selected = filter_presets(presets, args.vendor, args.name, args.generic, args.from_tool, args.not_for, system)
    out(f"{len(selected)} von {len(presets)} eigenen Filamentprofilen ausgewählt:")
    for p in selected:
        cloud = "Cloud" if p.synced else "lokal"
        out(f"  [{cloud}] {p.name} — {p.kind}, Hersteller: {p.shown_vendor}, Drucker: {_printers(p, system)}")
    synced = [p for p in selected if p.synced]
    local = [p for p in selected if not p.synced]
    if args.list_file:
        args.list_file.write_text(_cleanup_list(selected, user), encoding="utf-8")
        out(f"Liste geschrieben: {args.list_file}")
    if synced:
        out(f"{len(synced)} davon sind mit der Cloud synchronisiert. {CLOUD_HINT}")
    if not args.delete_local:
        out("Zum Löschen der lokalen Profile --delete-local angeben")
        return 0
    if not local:
        out("Keine lokalen Profile zum Löschen")
        return 0
    if args.dry_run:
        out(f"Probelauf: {len(local)} lokale Profile würden gelöscht")
        return 0
    if not _confirm(args, ask, f"{len(local)} lokale Profile löschen?"):
        out("Abgebrochen")
        return 1
    archive = backup(filament_dir, args.backup_dir, user)
    out(f"Backup: {archive}")
    for preset in local:
        delete_local(preset)
    out(f"{len(local)} lokale Profile gelöscht")
    return 0


def _printers(preset, system) -> str:
    printers = preset.printers(system)
    if printers is None:
        return "unbekannt"
    if not printers:
        return "alle"
    short = [p.replace("Bambu Lab ", "") for p in printers]
    return ", ".join(short[:3]) + (f" (+{len(short) - 3})" if len(short) > 3 else "")


def _cleanup_list(presets, user: str) -> str:
    lines = [
        f"# Filamentprofile zum Löschen (Benutzer {user})",
        "",
        "In Bambu Studio: Datei → Verwaltung von Batch-Profilen → Filament, diese Profile anhaken, Löschen.",
        "",
    ]
    for p in sorted(presets, key=lambda x: x.name.lower()):
        lines.append(f"- [ ] {p.name} ({'Cloud' if p.synced else 'lokal'}, {p.kind}, Hersteller: {p.shown_vendor})")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
