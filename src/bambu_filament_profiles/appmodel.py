"""Logic of the companion app, independent of the user interface.

Search the profile catalog, show values (from a source or inherited from the
base profile), install, and clean up existing profiles. Same safety rules as on
the command line: backup before every write, no silent overwrites, nothing
written while Bambu Studio is running, cloud profiles are not deleted locally.
"""

from __future__ import annotations

import contextlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path

from .catalog import list_profiles, read_build_info
from .install import (
    InstallError,
    Installation,
    active_user,
    apply_brand_merge,
    backup,
    brand_groups,
    bambu_running,
    checklist_markdown,
    delete_local,
    filter_presets,
    find_installations,
    plan_brand_merge,
    plan_install,
    printers_label,
    scan_user_presets,
    user_ids,
    write_profile,
)
from .sources.bambu import BambuProfiles

#: (key, label, unit) for the detail view.
DETAIL_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("nozzle_temperature", "Nozzle", "°C"),
    ("nozzle_temperature_initial_layer", "Nozzle first layer", "°C"),
    ("nozzle_temperature_range_low", "Nozzle min", "°C"),
    ("nozzle_temperature_range_high", "Nozzle max", "°C"),
    ("textured_plate_temp", "Textured PEI", "°C"),
    ("hot_plate_temp", "Smooth PEI / High Temp", "°C"),
    ("cool_plate_temp", "Cool Plate", "°C"),
    ("filament_max_volumetric_speed", "Max volumetric speed", "mm³/s"),
    ("filament_flow_ratio", "Flow ratio", ""),
    ("fan_min_speed", "Fan min", "%"),
    ("fan_max_speed", "Fan max", "%"),
    ("filament_density", "Density", "g/cm³"),
    ("filament_retraction_length", "Retraction", "mm"),
)


@dataclass
class CatalogItem:
    id: int
    brand: str
    material: str
    product: str
    name: str
    path: Path
    sources: list[str]

    def to_json(self, installed: bool) -> dict:
        return {
            "id": self.id,
            "brand": self.brand,
            "material": self.material,
            "product": self.product,
            "name": self.name,
            "sources": self.sources,
            "installed": installed,
        }


def load_catalog(profiles_dir: Path) -> list[CatalogItem]:
    profiles_dir = Path(profiles_dir)
    values_from = (read_build_info(profiles_dir) or {}).get("values_from") or {}
    items = []
    for index, entry in enumerate(list_profiles(profiles_dir)):
        spec = json.loads(entry["path"].read_text(encoding="utf-8"))
        relpath = entry["path"].relative_to(profiles_dir).as_posix()
        items.append(
            CatalogItem(
                id=index,
                brand=entry["brand"],
                material=entry["material"],
                product=entry["product"],
                name=spec["name"],
                path=entry["path"],
                sources=list(values_from.get(relpath, [])),
            )
        )
    return items


def search(items: list[CatalogItem], text: str = "", brand: str = "", material: str = "") -> list[CatalogItem]:
    """Every search word must appear in brand, material or product."""
    words = text.lower().split()
    result = []
    for item in items:
        if brand and item.brand.lower() != brand.lower():
            continue
        if material and item.material.lower() != material.lower():
            continue
        haystack = f"{item.brand} {item.material} {item.product}".lower()
        if all(word in haystack for word in words):
            result.append(item)
    return result


def details(item: CatalogItem, system: BambuProfiles | None) -> dict:
    """Values of a profile; missing ones come from the installation's base profile ("inherited")."""
    spec = json.loads(item.path.read_text(encoding="utf-8"))
    parent = spec.get("inherits", "")
    flat: dict = {}
    if system is not None and parent in system.presets:
        flat = system.flatten(parent)
    rows = []
    for key, label, unit in DETAIL_FIELDS:
        if key in spec:
            value, origin = spec[key], "source"
        elif key in flat:
            value, origin = flat[key], "inherited"
        else:
            continue
        value = value[0] if isinstance(value, list) and value else value
        if value in (None, "", "nil"):
            continue
        rows.append({"label": label, "value": str(value), "unit": unit, "origin": origin})
    return {
        "id": item.id,
        "name": item.name,
        "brand": item.brand,
        "material": item.material,
        "product": item.product,
        "parent": parent,
        "sources": item.sources,
        "rows": rows,
    }


class AppSession:
    """State of the app: catalog, chosen installation and user."""

    def __init__(
        self,
        profiles_dir: Path,
        backup_dir: Path,
        data_dir: str | None = None,
        installations=None,
        running=bambu_running,
        updater=None,
    ):
        self.profiles_dir = Path(profiles_dir)
        self._updater = updater
        self._updating = threading.Lock()
        self._load_catalog()
        self.backup_dir = Path(backup_dir)
        self._running = running
        if data_dir:
            self.installations = [Installation("manual", Path(data_dir).expanduser())]
        else:
            self.installations = list(installations) if installations is not None else find_installations()
        self.installation: Installation | None = None
        self.user = "default"
        self.system: BambuProfiles | None = None
        if self.installations:
            self.select(0)

    def _load_catalog(self) -> None:
        self.catalog = load_catalog(self.profiles_dir)
        self.by_id = {item.id: item for item in self.catalog}
        self.build_info = read_build_info(self.profiles_dir)

    @property
    def catalog_built(self) -> str | None:
        return self.build_info["built"] if self.build_info else None

    # ------------------------------------------------------------- selection

    def select(self, installation: int | None = None, user: str | None = None) -> None:
        if installation is not None:
            if not 0 <= installation < len(self.installations):
                raise InstallError("unknown installation")
            self.installation = self.installations[installation]
            ids = user_ids(self.installation.data_dir)
            active = active_user(self.installation.data_dir)
            self.user = active if active in ids else (ids[0] if ids else "default")
            try:
                self.system = BambuProfiles.from_installation(self.installation.data_dir)
            except FileNotFoundError:
                self.system = None
        if user is not None:
            if user not in user_ids(self._require().data_dir):
                raise InstallError(f"user folder \"{user}\" does not exist")
            self.user = user

    def _require(self) -> Installation:
        if self.installation is None:
            raise InstallError("no Bambu Studio installation found")
        return self.installation

    @property
    def filament_dir(self) -> Path:
        return self._require().data_dir / "user" / self.user / "filament"

    def running(self) -> bool:
        return bool(self._running())

    def _guard_write(self) -> None:
        if self.running():
            raise InstallError("Bambu Studio is running. Please close it and try again.")
        if self.system is None:
            raise InstallError("system profiles of the installation not found; start Bambu Studio once")

    # --------------------------------------------------------------- queries

    def state(self) -> dict:
        inst = self.installation
        return {
            "installations": [str(i) for i in self.installations],
            "installation": self.installations.index(inst) if inst else None,
            "data_dir": str(inst.data_dir) if inst else None,
            "users": user_ids(inst.data_dir) if inst else [],
            "active_user": active_user(inst.data_dir) if inst else None,
            "user": self.user if inst else None,
            "running": self.running(),
            "system_version": self.system.bundle_version if self.system else None,
            "catalog_size": len(self.catalog),
            "catalog_built": self.catalog_built,
            "can_update": self._updater is not None,
        }

    def _presets(self):
        if self.installation is None:
            return [], []
        return scan_user_presets(self.filament_dir)

    def profiles(self) -> list[dict]:
        installed = {p.name for p in self._presets()[0]}
        return [item.to_json(item.name in installed) for item in self.catalog]

    def profile(self, item_id: int) -> dict:
        if item_id not in self.by_id:
            raise InstallError("unknown profile")
        return details(self.by_id[item_id], self.system)

    def existing(self, generic: bool = False, not_for: str = "", text: str = "") -> dict:
        presets, problems = self._presets()
        selected = filter_presets(presets, generic_only=generic, not_for=not_for or None, system=self.system)
        words = text.lower().split()  # every word must match, like the search in "Find profiles"
        selected = [p for p in selected if all(w in p.name.lower() for w in words)]
        rows = [
            {
                "name": p.name,
                "kind": p.kind,
                "vendor": p.shown_vendor,
                "printers": printers_label(p, self.system),
                "cloud": p.synced,
                "from_tool": p.from_tool,
            }
            for p in selected
        ]
        return {"total": len(presets), "presets": rows, "problems": problems}

    # --------------------------------------------------------------- actions

    def _items(self, ids) -> list[CatalogItem]:
        unknown = [i for i in ids if i not in self.by_id]
        if unknown or not ids:
            raise InstallError("no or unknown profiles selected")
        return [self.by_id[i] for i in ids]

    def plan(self, ids) -> dict:
        self._require()
        if self.system is None:
            raise InstallError("system profiles of the installation not found; start Bambu Studio once")
        presets, _ = self._presets()
        actions, errors = plan_install([i.path for i in self._items(ids)], self.filament_dir, presets, self.system, self.user)
        return {"actions": [{"name": a.name, "kind": a.kind} for a in actions], "errors": errors}

    def install(self, ids, overwrite=()) -> dict:
        self._require()
        self._guard_write()
        presets, _ = self._presets()
        actions, errors = plan_install([i.path for i in self._items(ids)], self.filament_dir, presets, self.system, self.user)
        overwrite = set(overwrite)
        chosen = [a for a in actions if a.kind == "new" or (a.kind == "conflict" and a.name in overwrite)]
        skipped = [a.name for a in actions if a.kind == "conflict" and a.name not in overwrite]
        result = {"installed": [], "skipped": skipped, "errors": errors, "backup": None}
        if not chosen:
            return result
        result["backup"] = str(backup(self.filament_dir, self.backup_dir, self.user))
        for action in chosen:
            write_profile(action, self.user)
            result["installed"].append(action.name)
        return result

    def delete_local(self, names) -> dict:
        self._require()
        self._guard_write()
        wanted = set(names)
        presets, _ = self._presets()
        chosen = [p for p in presets if p.name in wanted]
        local = [p for p in chosen if not p.synced]
        refused = [p.name for p in chosen if p.synced]
        result = {"deleted": [], "refused": refused, "backup": None}
        if not local:
            return result
        result["backup"] = str(backup(self.filament_dir, self.backup_dir, self.user))
        for preset in local:
            delete_local(preset)
            result["deleted"].append(preset.name)
        return result

    def update(self, lock=None) -> dict:
        """Fetch the sources again and rebuild the catalog (writes nothing into Bambu Studio).

        The slow fetch and build run without ``lock``; only swapping in the new
        catalog holds it. A second update while one is running is refused.
        """
        if self._updater is None:
            raise InstallError("updating is not available here")
        if not self._updating.acquire(blocking=False):
            raise InstallError("an update is already running")
        try:
            log: list[str] = []
            self._updater(log.append)
            with lock if lock is not None else contextlib.nullcontext():
                self._load_catalog()
                return {"catalog_size": len(self.catalog), "catalog_built": self.catalog_built, "log": log[-8:]}
        finally:
            self._updating.release()

    # ------------------------------------------------------ brand spellings

    def _brand_groups(self):
        presets, _ = self._presets()
        system_vendors = self.system.vendors() if self.system else ()
        return presets, brand_groups(presets, system_vendors, {item.brand for item in self.catalog})

    def brands(self) -> dict:
        return {"groups": [group.to_json() for group in self._brand_groups()[1]]}

    def brand_plan(self, targets: dict) -> dict:
        presets, groups = self._brand_groups()
        return {"changes": [change.to_json() for change in plan_brand_merge(presets, groups, targets)]}

    def merge_brands(self, targets: dict) -> dict:
        self._require()
        self._guard_write()
        presets, groups = self._brand_groups()
        changes = plan_brand_merge(presets, groups, targets)
        result = {"renamed": [], "updated": [], "copied": [], "skipped": [c.preset.name for c in changes if c.kind == "skip"], "backup": None, "checklist": ""}
        if all(c.kind == "skip" for c in changes):
            return result
        result["backup"] = str(backup(self.filament_dir, self.backup_dir, self.user))
        done = apply_brand_merge(changes, self.user, presets)
        for key in ("renamed", "updated", "copied"):
            result[key] = done[key]
        if done["to_delete"]:
            result["checklist"] = checklist_markdown(done["to_delete"], self.user)
        return result

    def checklist(self, names) -> str:
        wanted = set(names)
        presets, _ = self._presets()
        return checklist_markdown([p for p in presets if p.name in wanted], self.user)
