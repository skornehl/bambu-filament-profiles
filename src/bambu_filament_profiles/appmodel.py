"""Logik der Begleit-App, unabhängig von der Oberfläche.

Suchen im Profil-Katalog, Werte anzeigen (aus der Quelle oder vom Basisprofil
geerbt), installieren und vorhandene Profile aufräumen. Dieselben Schutzregeln
wie auf der Kommandozeile: Backup vor jedem Schreiben, keine stillen
Überschreibungen, nichts schreiben, solange Bambu Studio läuft, Cloud-Profile
nicht lokal löschen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .catalog import list_profiles
from .install import (
    InstallError,
    Installation,
    active_user,
    backup,
    bambu_running,
    checklist_markdown,
    delete_local,
    filter_presets,
    find_installations,
    plan_install,
    printers_label,
    scan_user_presets,
    user_ids,
    write_profile,
)
from .sources.bambu import BambuProfiles

#: (Schlüssel, Bezeichnung, Einheit) für die Detailansicht.
DETAIL_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("nozzle_temperature", "Düse", "°C"),
    ("nozzle_temperature_initial_layer", "Düse erste Schicht", "°C"),
    ("nozzle_temperature_range_low", "Düse min.", "°C"),
    ("nozzle_temperature_range_high", "Düse max.", "°C"),
    ("textured_plate_temp", "Textured PEI", "°C"),
    ("hot_plate_temp", "Smooth PEI / High Temp", "°C"),
    ("cool_plate_temp", "Cool Plate", "°C"),
    ("filament_max_volumetric_speed", "Max. Volumenfluss", "mm³/s"),
    ("filament_flow_ratio", "Fluss", ""),
    ("fan_min_speed", "Lüfter min.", "%"),
    ("fan_max_speed", "Lüfter max.", "%"),
    ("filament_density", "Dichte", "g/cm³"),
    ("filament_retraction_length", "Rückzug", "mm"),
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


def parse_sources(description: str) -> list[str]:
    """„… Werte aus: OrcaSlicer, SpoolmanDB.“ → ["OrcaSlicer", "SpoolmanDB"]."""
    if "Werte aus:" not in description:
        return []
    tail = description.split("Werte aus:", 1)[1].strip().rstrip(".")
    return [s.strip() for s in tail.split(",") if s.strip() and s.strip() != "nur Basisprofil"]


def load_catalog(profiles_dir: Path) -> list[CatalogItem]:
    items = []
    for index, entry in enumerate(list_profiles(profiles_dir)):
        spec = json.loads(entry["path"].read_text(encoding="utf-8"))
        items.append(
            CatalogItem(
                id=index,
                brand=entry["brand"],
                material=entry["material"],
                product=entry["product"],
                name=spec["name"],
                path=entry["path"],
                sources=parse_sources(spec.get("description", "")),
            )
        )
    return items


def search(items: list[CatalogItem], text: str = "", brand: str = "", material: str = "") -> list[CatalogItem]:
    """Alle Suchwörter müssen in Hersteller, Material oder Sorte vorkommen."""
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
    """Werte eines Profils; fehlende kommen aus dem Basisprofil der Installation („geerbt“)."""
    spec = json.loads(item.path.read_text(encoding="utf-8"))
    parent = spec.get("inherits", "")
    flat: dict = {}
    if system is not None and parent in system.presets:
        flat = system.flatten(parent)
    rows = []
    for key, label, unit in DETAIL_FIELDS:
        if key in spec:
            value, origin = spec[key], "Quelle"
        elif key in flat:
            value, origin = flat[key], "geerbt"
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
    """Zustand der App: Katalog, gewählte Installation und Benutzer."""

    def __init__(self, profiles_dir: Path, backup_dir: Path, data_dir: str | None = None, installations=None, running=bambu_running):
        self.catalog = load_catalog(profiles_dir)
        self.by_id = {item.id: item for item in self.catalog}
        self.backup_dir = Path(backup_dir)
        self._running = running
        if data_dir:
            self.installations = [Installation("manuell", Path(data_dir).expanduser())]
        else:
            self.installations = list(installations) if installations is not None else find_installations()
        self.installation: Installation | None = None
        self.user = "default"
        self.system: BambuProfiles | None = None
        if self.installations:
            self.select(0)

    # ------------------------------------------------------------- Auswahl

    def select(self, installation: int | None = None, user: str | None = None) -> None:
        if installation is not None:
            if not 0 <= installation < len(self.installations):
                raise InstallError("Unbekannte Installation")
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
                raise InstallError(f"Benutzerordner „{user}“ gibt es nicht")
            self.user = user

    def _require(self) -> Installation:
        if self.installation is None:
            raise InstallError("Keine Bambu-Studio-Installation gefunden")
        return self.installation

    @property
    def filament_dir(self) -> Path:
        return self._require().data_dir / "user" / self.user / "filament"

    def running(self) -> bool:
        return bool(self._running())

    def _guard_write(self) -> None:
        if self.running():
            raise InstallError("Bambu Studio läuft. Bitte schließen und dann noch einmal versuchen.")
        if self.system is None:
            raise InstallError("Systemprofile der Installation nicht gefunden; Bambu Studio einmal starten")

    # -------------------------------------------------------------- Abfragen

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
            raise InstallError("Unbekanntes Profil")
        return details(self.by_id[item_id], self.system)

    def existing(self, generic: bool = False, not_for: str = "", text: str = "") -> dict:
        presets, problems = self._presets()
        selected = filter_presets(presets, names=text.split() if text else (), generic_only=generic, not_for=not_for or None, system=self.system)
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

    # ------------------------------------------------------------- Aktionen

    def _items(self, ids) -> list[CatalogItem]:
        unknown = [i for i in ids if i not in self.by_id]
        if unknown or not ids:
            raise InstallError("Keine oder unbekannte Profile ausgewählt")
        return [self.by_id[i] for i in ids]

    def plan(self, ids) -> dict:
        self._require()
        if self.system is None:
            raise InstallError("Systemprofile der Installation nicht gefunden; Bambu Studio einmal starten")
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

    def checklist(self, names) -> str:
        wanted = set(names)
        presets, _ = self._presets()
        return checklist_markdown([p for p in presets if p.name in wanted], self.user)
