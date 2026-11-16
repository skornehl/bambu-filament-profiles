"""Erzeugt aus einem abgeglichenen Eintrag ein Bambu-Studio-Benutzerprofil.

Das Profil ist ein eigenständiges Profil („custom root preset“), wie es der
Assistent „Filament erstellen“ von Bambu Studio anlegt: ``inherits`` ist leer,
alle Werte des passenden Generic-Profils stehen ausgeschrieben drin, dazu eine
eigene ``filament_id`` und der Hersteller. Nur so ordnet Bambu Studio das
Filament (AMS, Spulenverwaltung, Druckeranzeige) dem Hersteller zu statt
„Generic“, denn erbende Profile übernehmen die ``filament_id`` des Elternprofils.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

from . import MARKER, __version__
from .matching import family_of, match_key, safe_filename
from .merge import Merged, merge
from .model import Entry
from .sources import to_number
from .sources.bambu import BambuProfiles

DEFAULT_PRINTER = "Bambu Lab P1S 0.4 nozzle"


@dataclass(frozen=True)
class Limits:
    nozzle_max: float = 300
    bed_max: float = 100
    volumetric_max: float = 35


#: Grenzen je Drucker (Präfix des Bambu-Druckerprofils).
PRINTER_LIMITS = {"Bambu Lab P1S": Limits(nozzle_max=300, bed_max=100, volumetric_max=35)}

#: Basisprofil je Materialfamilie; die erste passende Regel gewinnt.
#: (Familie, nötige Token oder None, Kandidaten in Reihenfolge)
PARENT_RULES: tuple[tuple[str, frozenset[str] | None, tuple[str, ...]], ...] = (
    ("PLA", frozenset({"silk"}), ("Generic PLA Silk",)),
    ("PLA", frozenset({"cf", "gf"}), ("Generic PLA-CF",)),
    ("PLA", frozenset({"highspeed"}), ("Generic PLA High Speed @BBL X1C",)),
    ("PLA", None, ("Generic PLA",)),
    ("PETG", frozenset({"cf", "gf"}), ("Generic PETG-CF @BBL X1C",)),
    ("PETG", frozenset({"hf", "highspeed"}), ("Generic PETG HF @BBL P1S 0.4 nozzle", "Generic PETG HF @BBL X1C")),
    ("PETG", None, ("Generic PETG",)),
    ("PET", frozenset({"cf", "gf"}), ("Generic PETG-CF @BBL X1C",)),
    ("PET", None, ("Generic PETG",)),
    ("CPE", None, ("Generic PETG",)),
    ("PCTG", None, ("Generic PCTG @BBL X1C",)),
    ("ABS", None, ("Generic ABS",)),
    ("ASA", None, ("Generic ASA",)),
    ("TPU", None, ("Generic TPU",)),
    ("TPE", None, ("Generic TPU",)),
    ("PEBA", None, ("Generic TPU",)),
    ("PA", frozenset({"cf", "gf"}), ("Generic PA-CF",)),
    ("PA", None, ("Generic PA",)),
    ("PPA", frozenset({"gf"}), ("Generic PPA-GF @BBL X1C",)),
    ("PPA", frozenset({"cf"}), ("Generic PPA-CF @BBL X1C",)),
    ("PC", None, ("Generic PC @BBL P1S", "Generic PC")),
    ("PP", frozenset({"cf"}), ("Generic PP-CF @BBL X1C",)),
    ("PP", frozenset({"gf"}), ("Generic PP-GF @BBL X1C",)),
    ("PP", None, ("Generic PP @BBL X1C",)),
    ("PE", frozenset({"cf"}), ("Generic PE-CF @BBL X1C",)),
    ("PE", None, ("Generic PE @BBL X1C",)),
    ("PVA", None, ("Generic PVA",)),
    ("BVOH", None, ("Generic BVOH @BBL X1C",)),
    ("HIPS", None, ("Generic HIPS @BBL X1C",)),
    ("PHA", None, ("Generic PHA @BBL X1C",)),
    ("EVA", None, ("Generic EVA @BBL X1C",)),
)

INT_KEYS = frozenset(
    {
        "nozzle_temperature",
        "nozzle_temperature_initial_layer",
        "nozzle_temperature_range_low",
        "nozzle_temperature_range_high",
        "hot_plate_temp",
        "hot_plate_temp_initial_layer",
        "textured_plate_temp",
        "textured_plate_temp_initial_layer",
        "cool_plate_temp",
        "cool_plate_temp_initial_layer",
        "eng_plate_temp",
        "eng_plate_temp_initial_layer",
        "supertack_plate_temp",
        "supertack_plate_temp_initial_layer",
        "fan_min_speed",
        "fan_max_speed",
        "overhang_fan_speed",
        "additional_cooling_fan_speed",
        "close_fan_the_first_x_layers",
        "fan_cooling_layer_time",
        "slow_down_layer_time",
        "temperature_vitrification",
    }
)

#: Plausible Bereiche; Werte außerhalb werden verworfen (Warnung).
PLAUSIBLE = {
    "filament_density": (0.5, 3.5),
    "filament_flow_ratio": (0.7, 1.3),
    "fan_min_speed": (0, 100),
    "fan_max_speed": (0, 100),
    "overhang_fan_speed": (0, 100),
    "additional_cooling_fan_speed": (0, 100),
    "filament_retraction_length": (0, 10),
    "filament_retraction_speed": (1, 100),
}

DROP_FROM_BASE = frozenset(
    {
        "name",
        "inherits",
        "from",
        "setting_id",
        "instantiation",
        "filament_id",
        "type",
        "description",
        "compatible_printers",
        "compatible_printers_condition",
        "renamed_from",
        "base_id",
        "version",
    }
)

PLATES = ("hot", "textured")
OTHER_PLATES = ("cool", "eng", "supertack")

SOURCE_LABELS = {
    "manual": "eigene Werte",
    "orca": "OrcaSlicer",
    "prusa": "PrusaSlicer",
    "ofd": "Open Filament Database",
    "spoolman": "SpoolmanDB",
    "cura": "Cura",
    "derived": "abgeleitet",
}


@dataclass
class Issue:
    level: str  # "error" | "warning" | "info"
    message: str


@dataclass
class Generated:
    entry: Entry
    brand: str
    family: str
    product: str
    alias: str
    name: str
    parent: str | None = None
    profile: dict | None = None
    provenance: dict[str, str] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    merged: Merged | None = None

    @property
    def ok(self) -> bool:
        return self.profile is not None

    @property
    def relpath(self) -> str:
        return f"{safe_filename(self.brand)}/{safe_filename(self.family)}/{safe_filename(self.product)}.json"

    def error(self, message: str) -> Generated:
        self.issues.append(Issue("error", message))
        self.profile = None
        return self

    def warn(self, message: str) -> None:
        self.issues.append(Issue("warning", message))

    def note(self, message: str) -> None:
        self.issues.append(Issue("info", message))


def limits_for(printer: str) -> Limits:
    for prefix, limits in PRINTER_LIMITS.items():
        if printer.startswith(prefix):
            return limits
    return Limits()


def choose_parent(family: str, tokens: frozenset[str], bambu: BambuProfiles, printer: str) -> str | None:
    """Erste passende Regel gewinnt; fehlt deren Basisprofil, wird nicht geraten."""
    for rule_family, needed, candidates in PARENT_RULES:
        if rule_family != family:
            continue
        if needed is not None and not (needed & tokens):
            continue
        return next((c for c in candidates if bambu.is_compatible(c, printer)), None)
    return None


def product_name(entry: Entry) -> str:
    name = entry.name.strip()
    material = (entry.material or "").strip()
    if name.upper() == entry.family and material and material.upper() != entry.family and family_of(material) == entry.family:
        name = material  # Sorte „PLA“ mit Material „PLA+“ → „PLA+“
    if family_of(name) is None:
        material = (entry.material or entry.family).strip()
        name = f"{material} {name}".strip() if name.lower() != material.lower() else material
    return name.replace("@", " at ")


def filament_id_for(alias: str, user_id: str = "") -> str:
    """Wie der Bambu-Assistent: „P“ + 7 Zeichen MD5 aus Name (und Benutzer-ID)."""
    text = f"{alias}@{user_id}" if user_id else alias
    return "P" + hashlib.md5(text.encode("utf-8")).hexdigest()[:7]


def fmt(key: str, value: float) -> str:
    if key in INT_KEYS:
        return str(int(math.floor(value + 0.5)))
    return f"{value:g}"


def round5(value: float) -> float:
    return float(5 * math.floor(value / 5 + 0.5))


def generate(entry: Entry, bambu: BambuProfiles, printer: str = DEFAULT_PRINTER, system_keys: dict | None = None) -> Generated:
    brand = entry.brand.strip()
    product = product_name(entry)
    alias = f"{brand} {product}".strip()
    result = Generated(entry=entry, brand=brand, family=entry.family, product=product, alias=alias, name=f"{alias} @{printer}")
    merged = merge(entry)
    result.merged = merged
    for conflict in merged.conflicts:
        others = ", ".join(f"{SOURCE_LABELS.get(s, s)} {v:g}" for s, v in conflict.others.items())
        result.warn(f"{conflict.key}: {SOURCE_LABELS.get(conflict.chosen_source)} {conflict.chosen:g} gewählt, abweichend {others}")

    if system_keys:
        key = match_key(entry.brand, entry.material or entry.family, entry.name)
        if key in system_keys:
            result.note(f"Bambu Studio bringt dafür schon das Systemprofil „{system_keys[key]}“ mit")
            return result
    if brand.lower().replace(" ", "") in {"bambulab", "bambu"}:
        result.note("Bambu-Lab-Filamente haben Systemprofile in Bambu Studio")
        return result

    if merged.diameter is not None and abs(merged.diameter - 1.75) > 0.02:
        return result.error(f"Durchmesser {merged.diameter:g} mm, der Drucker braucht 1,75 mm")

    parent = choose_parent(entry.family, entry.tokens, bambu, printer)
    if parent is None:
        return result.error(f"kein passendes Basisprofil für {entry.family} auf „{printer}“")
    result.parent = parent
    base = bambu.flatten(parent)
    limits = limits_for(printer)
    values = dict(merged.values)
    provenance = dict(merged.provenance)

    for key, (low, high) in PLAUSIBLE.items():
        if key in values and not (low <= values[key] <= high):
            result.warn(f"{key} = {values[key]:g} unplausibel, verworfen")
            values.pop(key)
    if "filament_max_volumetric_speed" in values:
        mvs = values["filament_max_volumetric_speed"]
        if not (0 < mvs <= limits.volumetric_max):
            result.warn(f"Max. Volumenfluss {mvs:g} mm³/s unplausibel, verworfen")
            values.pop("filament_max_volumetric_speed")

    if not _nozzle(result, values, provenance, base, limits):
        return result
    if not _bed(result, values, provenance, base, limits):
        return result

    profile = {
        "name": result.name,
        "from": "User",
        "inherits": parent,
        "version": bambu.version,
        "description": _description(alias, parent, merged, provenance),
        "filament_settings_id": [result.name],
        "filament_vendor": [brand],
        "compatible_printers": [printer],
    }
    for key in sorted(values):
        if not key.startswith("_"):
            profile[key] = [fmt(key, values[key])]
    result.profile = profile
    result.provenance = {k: v for k, v in provenance.items() if not k.startswith("_")}
    return result


META_KEYS = ("name", "from", "inherits", "version", "description", "filament_settings_id", "filament_vendor", "compatible_printers")


class ExpandError(KeyError):
    pass


def expand(spec: dict, bambu: BambuProfiles, filament_id: str) -> dict:
    """Schlankes Profil (erbt vom Generic-Profil) zu einem eigenständigen ausschreiben.

    Das Ergebnis entspricht dem, was der Assistent „Filament erstellen“ anlegt:
    ``inherits`` leer, alle Werte des Basisprofils ausgeschrieben, eigene
    ``filament_id``. Werte je Hotend-Variante werden auf die Länge des
    Basisprofils vervielfältigt.
    """
    parent = spec.get("inherits") or ""
    try:
        base = bambu.flatten(parent)
    except KeyError as exc:
        raise ExpandError(f"Basisprofil „{parent}“ fehlt in dieser Bambu-Studio-Version") from exc
    root = {
        "name": spec["name"],
        "from": "User",
        "inherits": "",
        "version": bambu.version if bambu.bundle_version else spec.get("version", "2.0.0.0"),
        "filament_id": filament_id,
        "description": spec.get("description", ""),
        "filament_settings_id": [spec["name"]],
        "filament_vendor": spec.get("filament_vendor", ["Generic"]),
        "compatible_printers": spec.get("compatible_printers", []),
    }
    for key, value in base.items():
        if key not in DROP_FROM_BASE and key not in root:
            root[key] = value
    for key, value in spec.items():
        if key in META_KEYS:
            continue
        existing = base.get(key)
        if isinstance(value, list) and len(value) == 1 and isinstance(existing, list) and len(existing) > 1:
            value = value * len(existing)
        root[key] = value
    return root


def _nozzle(result: Generated, values: dict, provenance: dict, base: dict, limits: Limits) -> bool:
    low = values.get("nozzle_temperature_range_low")
    high = values.get("nozzle_temperature_range_high")
    if low is not None and high is not None and low > high:
        result.warn(f"Düsenbereich {low:g}–{high:g} °C verdreht, verworfen")
        values.pop("nozzle_temperature_range_low")
        values.pop("nozzle_temperature_range_high")
        low = high = None
    if low is not None and low > limits.nozzle_max:
        result.error(f"braucht mindestens {low:g} °C an der Düse, der Drucker schafft {limits.nozzle_max:g} °C")
        return False
    if high is not None and high > limits.nozzle_max:
        result.warn(f"Düsen-Obergrenze {high:g} °C auf {limits.nozzle_max:g} °C begrenzt")
        values["nozzle_temperature_range_high"] = high = float(limits.nozzle_max)
    for key in ("nozzle_temperature", "nozzle_temperature_initial_layer"):
        if key in values and values[key] > limits.nozzle_max:
            result.error(f"{key} = {values[key]:g} °C über der Druckergrenze {limits.nozzle_max:g} °C")
            return False
    lo = low if low is not None else -math.inf
    hi = high if high is not None else math.inf
    if "nozzle_temperature" not in values and (low is not None or high is not None):
        inherited = to_number(base.get("nozzle_temperature"))
        if inherited is not None and not (lo <= inherited <= hi):
            if low is not None and high is not None:
                derived = round5((low + high) / 2)
            else:
                derived = low if low is not None else high
            values["nozzle_temperature"] = derived
            provenance["nozzle_temperature"] = "derived"
            result.note(f"Düsentemperatur {derived:g} °C aus dem Bereich abgeleitet (Generic: {inherited:g} °C)")
    if "nozzle_temperature_initial_layer" not in values and "nozzle_temperature" in values:
        values["nozzle_temperature_initial_layer"] = values["nozzle_temperature"]
        provenance["nozzle_temperature_initial_layer"] = "derived"
    for key in ("nozzle_temperature", "nozzle_temperature_initial_layer"):
        if key in values and not (lo <= values[key] <= hi):
            result.warn(f"{key} = {values[key]:g} °C liegt außerhalb des Herstellerbereichs")
    if low is None and high is None and "nozzle_temperature" in values:
        base_low = to_number(base.get("nozzle_temperature_range_low"))
        base_high = to_number(base.get("nozzle_temperature_range_high"))
        if base_low is not None and base_high is not None and not (base_low <= values["nozzle_temperature"] <= base_high):
            result.warn(f"Düsentemperatur {values['nozzle_temperature']:g} °C liegt außerhalb des geerbten Bereichs {base_low:g}–{base_high:g} °C")
    return True


def _bed(result: Generated, values: dict, provenance: dict, base: dict, limits: Limits) -> bool:
    bmin = values.get("_bed_min")
    bmax = values.get("_bed_max")
    if bmin is not None and bmax is not None and bmin > bmax:
        result.warn(f"Bettbereich {bmin:g}–{bmax:g} °C verdreht, verworfen")
        bmin = bmax = None
    if bmin is not None and bmin > limits.bed_max:
        result.error(f"braucht mindestens {bmin:g} °C am Bett, der Drucker schafft {limits.bed_max:g} °C")
        return False
    lo = bmin if bmin is not None else -math.inf
    hi = bmax if bmax is not None else math.inf
    for plate in PLATES:
        key = f"{plate}_plate_temp"
        first = f"{key}_initial_layer"
        if key not in values and "_bed" in values:
            values[key] = values["_bed"]
            provenance[key] = provenance.get("_bed", "derived")
        if key not in values and (bmin is not None or bmax is not None):
            inherited = to_number(base.get(key))
            if inherited is not None and inherited > 0 and not (lo <= inherited <= hi):
                derived = round5((bmin + bmax) / 2) if bmin is not None and bmax is not None else (bmin if bmin is not None else bmax)
                values[key] = derived
                provenance[key] = "derived"
                result.note(f"{key} {derived:g} °C aus dem Bettbereich abgeleitet (Generic: {inherited:g} °C)")
        if first not in values:
            if "_bed_first" in values:
                values[first] = values["_bed_first"]
                provenance[first] = provenance.get("_bed_first", "derived")
            elif key in values:
                values[first] = values[key]
                provenance[first] = provenance.get(key, "derived")
        for k in (key, first):
            if k in values and values[k] > limits.bed_max:
                result.error(f"{k} = {values[k]:g} °C über der Druckergrenze {limits.bed_max:g} °C")
                return False
    for plate in OTHER_PLATES:
        for k in (f"{plate}_plate_temp", f"{plate}_plate_temp_initial_layer"):
            if k in values and not (0 <= values[k] <= limits.bed_max):
                result.warn(f"{k} = {values[k]:g} °C verworfen (Druckergrenze {limits.bed_max:g} °C)")
                values.pop(k)
    return True


def _description(alias: str, parent: str, merged: Merged, provenance: dict) -> str:
    used = []
    for source in ("manual", "orca", "prusa", "ofd", "spoolman", "cura"):
        if source in provenance.values() or source in {p for p in merged.provenance.values()}:
            used.append(SOURCE_LABELS[source])
    sources = ", ".join(used) if used else "nur Basisprofil"
    return f"{MARKER} {__version__}: {alias}. Basis {parent}. Werte aus: {sources}."
