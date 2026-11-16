"""Systemprofile von Bambu Studio (``resources/profiles/BBL``).

Sie liefern die Generic-Basisprofile, von denen die erzeugten Profile erben,
und zeigen, für welche Filamente Bambu Studio schon ein fertiges Profil hat.
"""

from __future__ import annotations

from pathlib import Path

from ..matching import alias_of, match_key
from . import read_json

PROFILE_DIR = Path("resources/profiles/BBL/filament")
BUNDLE_FILE = Path("resources/profiles/BBL.json")


class BambuProfiles:
    """Systemprofile aus dem Bambu-Studio-Quellcode oder einer lokalen Installation."""

    def __init__(self, root: Path, profile_dir: Path = PROFILE_DIR, bundle_file: Path = BUNDLE_FILE):
        self.root = Path(root)
        self.presets: dict[str, dict] = {}
        directory = self.root / profile_dir
        for path in sorted(directory.glob("*.json")):
            try:
                data = read_json(path)
            except ValueError:
                continue
            if isinstance(data, dict) and data.get("name"):
                self.presets[data["name"]] = data
        if not self.presets:
            raise FileNotFoundError(f"Keine Bambu-Filamentprofile unter {directory}")
        bundle = self.root / bundle_file
        self.bundle_version = read_json(bundle).get("version", "") if bundle.exists() else ""

    @classmethod
    def from_installation(cls, data_dir: Path) -> BambuProfiles:
        """Die Systemprofile, die die lokale Bambu-Studio-Installation gerade nutzt."""
        return cls(Path(data_dir) / "system", Path("BBL/filament"), Path("BBL.json"))

    @property
    def version(self) -> str:
        """Versionsnummer für Benutzerprofile, z. B. „02.09.00.74“ → „2.9.0.74“."""
        parts = [p for p in self.bundle_version.split(".") if p.strip()]
        try:
            numbers = [str(int(p)) for p in parts]
        except ValueError:
            numbers = []
        while len(numbers) < 4:
            numbers.append("0")
        return ".".join(numbers[:4]) if parts else "2.0.0.0"

    def resolve(self, name: str, key: str):
        seen = set()
        while name and name not in seen:
            seen.add(name)
            preset = self.presets.get(name)
            if preset is None:
                return None
            if key in preset:
                return preset[key]
            name = preset.get("inherits", "")
        return None

    def flatten(self, name: str) -> dict:
        """Alle Werte eines Profils inklusive der geerbten."""
        chain = []
        seen = set()
        while name and name not in seen:
            seen.add(name)
            preset = self.presets.get(name)
            if preset is None:
                raise KeyError(f"Basisprofil „{name}“ fehlt")
            chain.append(preset)
            name = preset.get("inherits", "")
        flat: dict = {}
        for preset in reversed(chain):
            flat.update(preset)
        return flat

    def is_compatible(self, name: str, printer: str) -> bool:
        preset = self.presets.get(name)
        if preset is None or preset.get("instantiation") != "true":
            return False
        printers = self.resolve(name, "compatible_printers") or []
        return not printers or printer in printers

    def system_keys(self, printer: str) -> dict[tuple, str]:
        """Abgleichschlüssel aller Nicht-Generic-Systemprofile für den Drucker."""
        keys: dict[tuple, str] = {}
        for name, preset in self.presets.items():
            if not self.is_compatible(name, printer):
                continue
            vendor = (self.resolve(name, "filament_vendor") or [""])[0]
            ftype = (self.resolve(name, "filament_type") or [""])[0]
            if vendor == "Generic":
                continue
            alias = alias_of(name)
            product = alias[len(vendor):].strip() if alias.lower().startswith(vendor.lower()) else alias
            key = match_key(vendor, ftype, product)
            if key:
                keys[key] = alias
        return keys
