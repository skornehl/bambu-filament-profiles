"""Lokale Bambu-Studio-Installation finden, Profile installieren und aufräumen.

Bambu Studio liest Benutzerprofile aus ``<Datenordner>/user/<Benutzer>/filament``.
Eigenständige Profile (eigener Hersteller) liegen im Unterordner ``base``.
``<Benutzer>`` ist die Bambu-Konto-ID oder ``default`` ohne Anmeldung; die
aktive steht in ``BambuStudio.conf`` unter ``app.preset_folder``.

Wichtig für das Löschen: Ist ein Profil mit der Cloud synchronisiert (die
``.info``-Datei hat eine ``setting_id``), lädt Bambu Studio es beim nächsten
Start wieder herunter, wenn nur die lokale Datei fehlt. Solche Profile löscht
man in Bambu Studio selbst (Datei → Verwaltung von Batch-Profilen).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import MARKER
from .generate import ExpandError, expand, filament_id_for
from .matching import alias_of
from .sources.bambu import BambuProfiles

APP_DIR = "BambuStudio"
FLATPAK_ID = "com.bambulab.BambuStudio"
PROCESS_NAMES = frozenset(
    {"bambu-studio", "bambustudio", "bambu_studio", "bambustu_main", "bambu-studio.exe", "bambustudio.exe"}
)


class InstallError(RuntimeError):
    pass


@dataclass
class Installation:
    kind: str
    data_dir: Path

    def __str__(self) -> str:
        return f"{self.kind}: {self.data_dir}"


@dataclass
class UserPreset:
    name: str
    path: Path
    root: bool
    inherits: str
    vendor: str
    filament_id: str
    setting_id: str
    from_tool: bool
    compatible_printers: tuple[str, ...] = ()

    @property
    def synced(self) -> bool:
        return bool(self.setting_id)

    def printers(self, system: BambuProfiles | None = None) -> list[str] | None:
        """Drucker, für die Bambu Studio das Profil anbietet; ``None`` = nicht bestimmbar.

        Eigene Angabe → bei eigenständigen Profilen der Namenszusatz „@Drucker“ (so setzt es
        Bambu Studio beim Laden) → bei erbenden das Elternprofil der Installation.
        Eine leere Liste heißt: für alle Drucker.
        """
        if self.compatible_printers:
            return list(self.compatible_printers)
        if self.root:
            return [self.name.split("@", 1)[1].strip()] if "@" in self.name else []
        if system is None:
            return None
        resolved = system.resolve(self.inherits, "compatible_printers")
        return None if resolved is None else list(resolved)

    def usable_on(self, printer: str, system: BambuProfiles | None = None) -> bool | None:
        printers = self.printers(system)
        if printers is None:
            return None
        return not printers or any(printer.lower() in p.lower() for p in printers)

    @property
    def shown_vendor(self) -> str:
        """Hersteller, unter dem Bambu Studio das Filament führt."""
        if self.root:
            return self.vendor or "?"
        if self.inherits.startswith("Generic"):
            return "Generic"
        return f"wie {self.inherits}"

    @property
    def kind(self) -> str:
        return "eigenständig" if self.root else f"erbt von {self.inherits}"


@dataclass
class Action:
    kind: str  # "new" | "same" | "conflict"
    source: Path
    target: Path
    name: str
    data: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- Suche


def candidate_dirs(platform: str | None = None, env: dict | None = None, home: Path | None = None) -> list[Installation]:
    platform = platform or sys.platform
    env = os.environ if env is None else env
    home = Path.home() if home is None else Path(home)
    if platform.startswith("win"):
        appdata = env.get("APPDATA")
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
        return [Installation("windows", base / APP_DIR)]
    if platform == "darwin":
        return [Installation("macos", home / "Library" / "Application Support" / APP_DIR)]
    config_home = Path(env["XDG_CONFIG_HOME"]) if env.get("XDG_CONFIG_HOME") else home / ".config"
    return [
        Installation("linux", config_home / APP_DIR),
        Installation("flatpak", home / ".var" / "app" / FLATPAK_ID / "config" / APP_DIR),
    ]


def find_installations(platform: str | None = None, env: dict | None = None, home: Path | None = None) -> list[Installation]:
    found = []
    for inst in candidate_dirs(platform, env, home):
        if (inst.data_dir / "BambuStudio.conf").is_file() or (inst.data_dir / "user").is_dir():
            found.append(inst)
    return found


def active_user(data_dir: Path) -> str | None:
    conf = Path(data_dir) / "BambuStudio.conf"
    try:
        data = json.loads(conf.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = (data.get("app") or {}).get("preset_folder") if isinstance(data, dict) else None
    return value or None


def user_ids(data_dir: Path) -> list[str]:
    root = Path(data_dir) / "user"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def choose_installation(found: list[Installation], data_dir: str | None, ask) -> Installation:
    if data_dir:
        path = Path(data_dir).expanduser()
        if not path.is_dir():
            raise InstallError(f"Datenordner {path} gibt es nicht")
        return Installation("manuell", path)
    if not found:
        raise InstallError("Keine Bambu-Studio-Installation gefunden. Mit --data-dir den Datenordner angeben.")
    if len(found) == 1:
        return found[0]
    return _pick(found, "Mehrere Bambu-Studio-Installationen gefunden", ask, str)


def choose_user(data_dir: Path, requested: str | None, ask) -> str:
    ids = user_ids(data_dir)
    if requested:
        if requested not in ids:
            raise InstallError(f"Benutzerordner „{requested}“ gibt es nicht (vorhanden: {', '.join(ids) or 'keiner'})")
        return requested
    active = active_user(data_dir)
    if not ids:
        return active or "default"
    if len(ids) == 1:
        return ids[0]
    ordered = ([active] if active in ids else []) + [i for i in ids if i != active]
    return _pick(ordered, "Mehrere Benutzerordner gefunden" + (f" (aktiv: {active})" if active else ""), ask, str)


def _pick(options, title: str, ask, label):
    if ask is None:
        raise InstallError(title + ": " + ", ".join(label(o) for o in options) + ". Bitte per Option auswählen.")
    lines = [title + ":"] + [f"  {i + 1}) {label(o)}" for i, o in enumerate(options)]
    answer = ask("\n".join(lines) + "\nNummer [1]: ").strip() or "1"
    if not answer.isdigit() or not 1 <= int(answer) <= len(options):
        raise InstallError("Ungültige Auswahl")
    return options[int(answer) - 1]


# --------------------------------------------------------------------- Prozesse


def bambu_running(platform: str | None = None, proc_root: Path = Path("/proc"), run=subprocess.run) -> bool:
    platform = platform or sys.platform
    if platform.startswith("win"):
        try:
            out = run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=False).stdout
        except OSError:
            return False
        return any(name in out.lower() for name in ("bambu-studio.exe", "bambustudio.exe"))
    if platform == "darwin":
        try:
            return run(["pgrep", "-x", "BambuStudio"], capture_output=True, check=False).returncode == 0
        except OSError:
            return False
    try:
        entries = list(Path(proc_root).iterdir())
    except OSError:
        return False
    return any(_is_bambu_process(entry) for entry in entries if entry.name.isdigit())


def _is_bambu_process(entry: Path) -> bool:
    """Prozessname (``comm``) oder Programmname (erstes Argument) gehört zu Bambu Studio.

    Der Flatpak-Hauptprozess heißt ``bambustu_main`` (Name des Hauptthreads), sein
    Programm ist ``/app/bin/bambu-studio``. Nur das erste Argument zählt, damit eine
    Shell mit „bambu-studio“ irgendwo im Befehl keinen Fehlalarm auslöst.
    """
    try:
        comm = (entry / "comm").read_text(encoding="utf-8", errors="replace").strip().lower()
    except OSError:
        comm = ""
    if comm in PROCESS_NAMES:
        return True
    try:
        argv0 = (entry / "cmdline").read_bytes().split(b"\0", 1)[0].decode("utf-8", errors="replace")
    except OSError:
        return False
    program = argv0.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return program in PROCESS_NAMES or (program.endswith(".appimage") and "bambu" in program)


# ------------------------------------------------------------ vorhandene Profile


def read_info(path: Path) -> dict[str, str]:
    info: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                info[key.strip()] = value.strip()
    except OSError:
        pass
    return info


def scan_user_presets(filament_dir: Path) -> tuple[list[UserPreset], list[str]]:
    presets: list[UserPreset] = []
    problems: list[str] = []
    for folder in (filament_dir / "base", filament_dir):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                problems.append(f"{path.name}: nicht lesbar ({exc})")
                continue
            info = read_info(path.with_suffix(".info"))
            setting_id = info.get("setting_id", "")
            presets.append(
                UserPreset(
                    name=path.stem,
                    path=path,
                    root=not data.get("inherits"),
                    inherits=data.get("inherits", ""),
                    vendor=(data.get("filament_vendor") or [""])[0],
                    filament_id=data.get("filament_id", ""),
                    setting_id="" if setting_id in ("", "null") else setting_id,
                    from_tool=MARKER in str(data.get("description", "")),
                    compatible_printers=tuple(data.get("compatible_printers") or ()),
                )
            )
    return presets, problems


def filter_presets(presets, vendors=(), names=(), generic_only=False, tool_only=False, not_for: str | None = None, system=None):
    """Auswahl für ``cleanup``. ``not_for``: nur Profile, die sicher nicht für diesen Drucker gelten."""
    result = []
    for preset in presets:
        if not_for and preset.usable_on(not_for, system) is not False:
            continue
        if vendors and not any(v.lower() in (preset.vendor or preset.name).lower() or v.lower() in preset.name.lower() for v in vendors):
            continue
        if names and not any(n.lower() in preset.name.lower() for n in names):
            continue
        if generic_only and preset.shown_vendor != "Generic":
            continue
        if tool_only and not preset.from_tool:
            continue
        result.append(preset)
    return result


# ----------------------------------------------------------------- Installation


def plan_install(profile_files: list[Path], filament_dir: Path, existing: list[UserPreset], bambu: BambuProfiles, user_id: str):
    """Aktionen planen; liefert (Aktionen, Fehlermeldungen)."""
    by_name = {p.name: p for p in existing}
    actions: list[Action] = []
    errors: list[str] = []
    for source in profile_files:
        spec = json.loads(Path(source).read_text(encoding="utf-8"))
        name = spec["name"]
        try:
            data = expand(spec, bambu, assign_filament_id(name, user_id, existing))
        except ExpandError as exc:
            errors.append(f"{name}: {exc.args[0]}")
            continue
        target = filament_dir / "base" / f"{name}.json"
        current = by_name.get(name)
        if current is None:
            kind = "new"
        else:
            try:
                same = json.loads(current.path.read_text(encoding="utf-8")) == data
            except (OSError, ValueError):
                same = False
            kind = "same" if same else "conflict"
            target = current.path
        actions.append(Action(kind, Path(source), target, name, data))
    return actions, errors


def assign_filament_id(name: str, user_id: str, existing: list[UserPreset]) -> str:
    """Wie der Bambu-Assistent: gleicher Name → gleiche ID, sonst neue ohne Kollision."""
    alias = alias_of(name)
    taken: dict[str, set[str]] = {}
    for preset in existing:
        if preset.filament_id:
            taken.setdefault(preset.filament_id, set()).add(alias_of(preset.name))
            if preset.root and alias_of(preset.name) == alias:
                return preset.filament_id
    uid = user_id if user_id.isdigit() else ""
    candidate = filament_id_for(alias, uid)
    counter = 0
    while candidate in taken and alias not in taken[candidate]:
        counter += 1
        candidate = filament_id_for(f"{alias}#{counter}", uid)
    return candidate


def backup(filament_dir: Path, backup_dir: Path, label: str) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"filament-{label}-{stamp}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        if filament_dir.is_dir():
            for path in sorted(filament_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(filament_dir.parent))
    return target


def write_profile(action: Action, user_id: str, now: float | None = None) -> None:
    action.target.parent.mkdir(parents=True, exist_ok=True)
    action.target.write_text(json.dumps(action.data, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    stamp = int(now if now is not None else time.time())
    info = [
        "sync_info = ",
        f"user_id = {user_id if user_id.isdigit() else ''}",
        "setting_id = ",
        "base_id = ",
        f"updated_time = {stamp}",
    ]
    action.target.with_suffix(".info").write_text("\n".join(info) + "\n", encoding="utf-8")


def delete_local(preset: UserPreset) -> None:
    if preset.synced:
        raise InstallError(f"„{preset.name}“ ist mit der Cloud synchronisiert und käme zurück; bitte in Bambu Studio löschen")
    preset.path.unlink(missing_ok=True)
    preset.path.with_suffix(".info").unlink(missing_ok=True)


def printers_label(preset: UserPreset, system: BambuProfiles | None) -> str:
    """Kurzanzeige der Drucker, z. B. „P1S 0.4 nozzle, X1 0.4 nozzle (+2)“."""
    printers = preset.printers(system)
    if printers is None:
        return "unbekannt"
    if not printers:
        return "alle"
    short = [p.replace("Bambu Lab ", "") for p in printers]
    return ", ".join(short[:3]) + (f" (+{len(short) - 3})" if len(short) > 3 else "")


def checklist_markdown(presets: list[UserPreset], user: str) -> str:
    """Liste zum Abhaken für Datei → Verwaltung von Batch-Profilen in Bambu Studio."""
    lines = [
        f"# Filamentprofile zum Löschen (Benutzer {user})",
        "",
        "In Bambu Studio: Datei → Verwaltung von Batch-Profilen → Filament, diese Profile anhaken, Löschen.",
        "",
    ]
    for p in sorted(presets, key=lambda x: x.name.lower()):
        lines.append(f"- [ ] {p.name} ({'Cloud' if p.synced else 'lokal'}, {p.kind}, Hersteller: {p.shown_vendor})")
    return "\n".join(lines) + "\n"


def default_data_dir(platform: str | None = None, env: dict | None = None, home: Path | None = None) -> Path:
    """Ablage für Backups und Quellen-Cache dieses Tools."""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    home = Path.home() if home is None else Path(home)
    if platform.startswith("win"):
        base = Path(env["LOCALAPPDATA"]) if env.get("LOCALAPPDATA") else home / "AppData" / "Local"
    elif platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(env["XDG_DATA_HOME"]) if env.get("XDG_DATA_HOME") else home / ".local" / "share"
    return base / "bambu-filament-profiles"
