"""Find the local Bambu Studio installation, install profiles and clean up.

Bambu Studio reads user profiles from ``<data folder>/user/<user>/filament``.
Standalone profiles (own brand) live in the ``base`` subfolder. ``<user>`` is
the Bambu account ID, or ``default`` when not logged in; the active one is
stored in ``BambuStudio.conf`` under ``app.preset_folder``.

Important for deleting: if a profile is synced with the cloud (its ``.info``
file has a ``setting_id``), Bambu Studio downloads it again on the next start
when only the local file is gone. Delete such profiles in Bambu Studio itself
(File → Batch Preset Management).
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
from .matching import UNSAFE_FILENAME_CHARS, alias_of, norm_brand
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
        """Printers Bambu Studio offers the profile for; ``None`` = cannot be determined.

        Own setting → for standalone profiles the "@printer" name suffix (that is what
        Bambu Studio uses when loading) → for inheriting ones the installation's parent.
        An empty list means: all printers.
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
        """Brand under which Bambu Studio files the filament."""
        if self.root:
            return self.vendor or "?"
        if self.inherits.startswith("Generic"):
            return "Generic"
        return f"as {self.inherits}"

    @property
    def kind(self) -> str:
        return "standalone" if self.root else f"inherits {self.inherits}"


@dataclass
class Action:
    kind: str  # "new" | "same" | "conflict"
    source: Path
    target: Path
    name: str
    data: dict = field(default_factory=dict)


# -------------------------------------------------------------------------- search


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
            raise InstallError(f"data folder {path} does not exist")
        return Installation("manual", path)
    if not found:
        raise InstallError("no Bambu Studio installation found; pass the data folder with --data-dir")
    if len(found) == 1:
        return found[0]
    return _pick(found, "Several Bambu Studio installations found", ask, str)


def choose_user(data_dir: Path, requested: str | None, ask) -> str:
    ids = user_ids(data_dir)
    if requested:
        if requested not in ids:
            raise InstallError(f"user folder \"{requested}\" does not exist (available: {', '.join(ids) or 'none'})")
        return requested
    active = active_user(data_dir)
    if not ids:
        return active or "default"
    if len(ids) == 1:
        return ids[0]
    ordered = ([active] if active in ids else []) + [i for i in ids if i != active]
    return _pick(ordered, "Several user folders found" + (f" (active: {active})" if active else ""), ask, str)


def _pick(options, title: str, ask, label):
    if ask is None:
        raise InstallError(title + ": " + ", ".join(label(o) for o in options) + ". Please choose one with an option.")
    lines = [title + ":"] + [f"  {i + 1}) {label(o)}" for i, o in enumerate(options)]
    answer = ask("\n".join(lines) + "\nNumber [1]: ").strip() or "1"
    if not answer.isdigit() or not 1 <= int(answer) <= len(options):
        raise InstallError("invalid choice")
    return options[int(answer) - 1]


# ------------------------------------------------------------------- processes


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
    """Process name (``comm``) or program name (first argument) belongs to Bambu Studio.

    The Flatpak main process is called ``bambustu_main`` (name of the main thread),
    its program is ``/app/bin/bambu-studio``. Only the first argument counts, so a
    shell with "bambu-studio" somewhere in its command line raises no false alarm.
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


# ------------------------------------------------------------ existing profiles


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
                problems.append(f"{path.name}: unreadable ({exc})")
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
    """Selection for ``cleanup``. ``not_for``: only profiles that certainly do not apply to this printer."""
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


# ------------------------------------------------------------------ installation


def plan_install(profile_files: list[Path], filament_dir: Path, existing: list[UserPreset], bambu: BambuProfiles, user_id: str):
    """Plan the actions; returns (actions, error messages)."""
    by_name = {p.name: p for p in existing}
    actions: list[Action] = []
    errors: list[str] = []
    reserved: dict[str, str] = {}
    for source in profile_files:
        spec = json.loads(Path(source).read_text(encoding="utf-8"))
        name = spec["name"]
        if UNSAFE_FILENAME_CHARS.search(name):
            # Bambu Studio stores the preset as <name>.json; "/" would create a subfolder.
            errors.append(f"{name}: name cannot be used as a file name; run \"bfp update\"")
            continue
        filament_id = assign_filament_id(name, user_id, existing, reserved)
        try:
            data = expand(spec, bambu, filament_id)
        except ExpandError as exc:
            errors.append(f"{name}: {exc.args[0]}")
            continue
        reserved[filament_id] = alias_of(name)
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


def assign_filament_id(name: str, user_id: str, existing: list[UserPreset], reserved: dict[str, str] | None = None) -> str:
    """Like the Bambu wizard: same name → same ID, otherwise a new one without collision.

    ``reserved`` maps IDs already handed out in the same run to their alias.
    """
    alias = alias_of(name)
    taken: dict[str, set[str]] = {}
    for preset in existing:
        if preset.filament_id:
            taken.setdefault(preset.filament_id, set()).add(alias_of(preset.name))
            if preset.root and alias_of(preset.name) == alias:
                return preset.filament_id
    for filament_id, other in (reserved or {}).items():
        taken.setdefault(filament_id, set()).add(other)
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
    counter = 1
    while target.exists():  # never replace an earlier backup from the same second
        counter += 1
        target = backup_dir / f"filament-{label}-{stamp}-{counter}.zip"
    with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED) as archive:
        if filament_dir.is_dir():
            for path in sorted(filament_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(filament_dir.parent))
    return target


def write_profile(action: Action, user_id: str, now: float | None = None) -> None:
    """Write the preset and its ``.info``.

    When an existing preset is overwritten, its cloud link (``setting_id``,
    ``user_id``) is kept and a synced preset is marked ``sync_info = update``, so
    Bambu Studio uploads the change to the same cloud preset instead of pulling
    the old one back or creating a duplicate.
    """
    info_path = action.target.with_suffix(".info")
    old = read_info(info_path) if action.target.exists() else {}
    action.target.parent.mkdir(parents=True, exist_ok=True)
    action.target.write_text(json.dumps(action.data, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    stamp = int(now if now is not None else time.time())
    info = {
        "sync_info": "update" if old.get("setting_id") else old.get("sync_info", ""),
        "user_id": old.get("user_id") or (user_id if user_id.isdigit() else ""),
        "setting_id": old.get("setting_id", ""),
        "base_id": "",  # standalone preset: no system parent
        "updated_time": str(stamp),
    }
    info_path.write_text("".join(f"{key} = {value}\n" for key, value in info.items()), encoding="utf-8")


def delete_local(preset: UserPreset) -> None:
    if preset.synced:
        raise InstallError(f"\"{preset.name}\" is synced with the cloud and would come back; please delete it in Bambu Studio")
    preset.path.unlink(missing_ok=True)
    preset.path.with_suffix(".info").unlink(missing_ok=True)


# ----------------------------------------------------------- brand spellings


@dataclass
class BrandGroup:
    """One brand that Bambu Studio would list under several spellings."""

    key: str
    spellings: list[str]
    target: str
    reason: str  # where the target spelling comes from
    presets: list[UserPreset]  # standalone presets spelled differently from the target

    def to_json(self) -> dict:
        return {"key": self.key, "spellings": self.spellings, "target": self.target, "reason": self.reason, "presets": [p.name for p in self.presets]}


@dataclass
class BrandChange:
    preset: UserPreset
    new_name: str
    vendor: str
    kind: str  # "rename" (local) | "update" (cloud, same name) | "copy" (cloud: new preset, delete the old one in Bambu Studio) | "skip"
    reason: str = ""

    def to_json(self) -> dict:
        return {"name": self.preset.name, "new_name": self.new_name, "vendor": self.vendor, "kind": self.kind, "reason": self.reason}


def brand_groups(presets: list[UserPreset], system_vendors=(), catalog_brands=()) -> list[BrandGroup]:
    """Brands of standalone presets that appear under more than one spelling.

    A spelling counts when one of your standalone presets uses it, when Bambu Studio uses it for its own system
    filaments, or when the catalog uses it (so that later installs land under the same name). The proposed
    spelling is Bambu Studio's, else the catalog's, else the one most of your presets use.
    """
    own: dict[str, dict[str, list[UserPreset]]] = {}
    for preset in presets:
        if preset.root and preset.vendor:
            own.setdefault(norm_brand(preset.vendor), {}).setdefault(preset.vendor, []).append(preset)
    system = {norm_brand(v): v for v in sorted(system_vendors) if v != "Generic"}
    catalog = {norm_brand(b): b for b in sorted(catalog_brands)}
    groups = []
    for key, by_spelling in sorted(own.items()):
        spellings = set(by_spelling) | {s for s in (system.get(key), catalog.get(key)) if s}
        if len(spellings) < 2:
            continue
        if key in system:
            target, reason = system[key], "Bambu Studio"
        elif key in catalog:
            target, reason = catalog[key], "catalog"
        else:
            target = max(sorted(by_spelling), key=lambda s: len(by_spelling[s]))
            reason = "most of your profiles"
        others = [p for spelling, items in by_spelling.items() if spelling != target for p in items]
        groups.append(BrandGroup(key, sorted(spellings, key=str.lower), target, reason, sorted(others, key=lambda p: p.name.lower())))
    return groups


def _rebrand(name: str, old: str, new: str) -> str:
    """"eSUN 3D PETG @…" → "eSUN PETG @…"; names that do not start with the brand stay as they are."""
    if name.lower().startswith(old.lower()) and name[len(old) : len(old) + 1] in ("", " "):
        return new + name[len(old) :]
    return name


def plan_brand_merge(presets: list[UserPreset], groups: list[BrandGroup], targets: dict[str, str] | None = None) -> list[BrandChange]:
    """What merging the spellings would do; ``targets`` overrides the proposed spelling per group key."""
    # Compared case-insensitively: Windows and macOS cannot hold "Tinmorry PLA" and "TINMORRY PLA" side by side.
    by_name: dict[str, list[UserPreset]] = {}
    for p in presets:
        by_name.setdefault(p.name.lower(), []).append(p)
    taken: set[str] = set()
    changes = []
    for group in groups:
        target = (targets or {}).get(group.key) or group.target
        if norm_brand(target) != group.key or UNSAFE_FILENAME_CHARS.search(target):
            raise InstallError(f"\"{target}\" is not a spelling of this brand")
        members = [p for p in presets if p.root and p.vendor and norm_brand(p.vendor) == group.key and p.vendor != target]
        for preset in members:
            new_name = _rebrand(preset.name, preset.vendor, target)
            others = [p for p in by_name.get(new_name.lower(), []) if p is not preset]
            if others or new_name.lower() in taken:
                changes.append(BrandChange(preset, new_name, target, "skip", f"a profile named \"{new_name}\" already exists"))
                continue
            taken.add(new_name.lower())
            if not preset.synced:
                kind = "rename"
            elif new_name.lower() == preset.name.lower():
                kind = "update"  # same file: keep the cloud link and update the cloud preset
            else:
                kind = "copy"
            changes.append(BrandChange(preset, new_name, target, kind))
    return changes


def apply_brand_merge(changes: list[BrandChange], user_id: str, presets: list[UserPreset]) -> dict:
    """Carry out a plan. Local presets are renamed in place; a synced preset that needs a new name gets a new copy,
    and the old one must be deleted in Bambu Studio (it is returned in ``to_delete``)."""
    result: dict[str, list] = {"renamed": [], "updated": [], "copied": [], "skipped": [], "to_delete": []}
    reserved: dict[str, str] = {}
    for change in changes:
        preset = change.preset
        if change.kind == "skip":
            result["skipped"].append(preset.name)
            continue
        data = json.loads(preset.path.read_text(encoding="utf-8"))
        data["name"] = change.new_name
        data["filament_settings_id"] = [change.new_name]
        data["filament_vendor"] = [change.vendor]
        target = preset.path.with_name(f"{change.new_name}.json")
        if change.kind == "copy":
            # A new preset, uploaded as new; the old cloud preset stays until it is deleted in Bambu Studio.
            data["filament_id"] = assign_filament_id(change.new_name, user_id, presets, reserved)
            reserved[data["filament_id"]] = alias_of(change.new_name)
            write_profile(Action("new", preset.path, target, change.new_name, data), user_id)
            result["copied"].append(change.new_name)
            result["to_delete"].append(preset)
            continue
        write_profile(Action("conflict", preset.path, preset.path, change.new_name, data), user_id)
        if target.name != preset.path.name:
            for old, new in ((preset.path, target), (preset.path.with_suffix(".info"), target.with_suffix(".info"))):
                _rename(old, new)
        result["renamed" if change.kind == "rename" else "updated"].append(change.new_name)
    return result


def _rename(old: Path, new: Path) -> None:
    """Rename, also when only upper/lower case changes (Windows and macOS treat both names as the same file)."""
    step = old.with_name(old.name + ".renaming")
    old.rename(step)
    step.rename(new)


def printers_label(preset: UserPreset, system: BambuProfiles | None) -> str:
    """Short printer label, e.g. "P1S 0.4 nozzle, X1 0.4 nozzle (+2)"."""
    printers = preset.printers(system)
    if printers is None:
        return "unknown"
    if not printers:
        return "all"
    short = [p.replace("Bambu Lab ", "") for p in printers]
    return ", ".join(short[:3]) + (f" (+{len(short) - 3})" if len(short) > 3 else "")


def checklist_markdown(presets: list[UserPreset], user: str) -> str:
    """Checklist for File → Batch Preset Management in Bambu Studio."""
    lines = [
        f"# Filament profiles to delete (user {user})",
        "",
        "In Bambu Studio: File → Batch Preset Management → Filament, tick these profiles, Delete.",
        "",
    ]
    for p in sorted(presets, key=lambda x: x.name.lower()):
        lines.append(f"- [ ] {p.name} ({'cloud' if p.synced else 'local'}, {p.kind}, brand: {p.shown_vendor})")
    return "\n".join(lines) + "\n"


def default_data_dir(platform: str | None = None, env: dict | None = None, home: Path | None = None) -> Path:
    """Folder for this tool's backups, sources and profiles."""
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
