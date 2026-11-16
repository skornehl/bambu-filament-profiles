"""Turn a matched entry into a Bambu Studio user profile.

The profile is a standalone profile ("custom root preset"), just like the one
Bambu Studio's "Create filament" wizard creates: ``inherits`` is empty, all
values of the matching Generic profile are written out, plus its own
``filament_id`` and the brand. Only then does Bambu Studio file the filament
(AMS, spool management, printer display) under its brand instead of "Generic",
because inheriting profiles take over the parent's ``filament_id``.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

from . import MARKER, __version__
from .matching import clean_name, family_of, match_key, safe_filename
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


#: Limits per printer (prefix of the Bambu printer profile).
PRINTER_LIMITS = {"Bambu Lab P1S": Limits(nozzle_max=300, bed_max=100, volumetric_max=35)}

#: Base profile per material family; the first matching rule wins.
#: (family, required tokens or None, candidates in order)
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

#: Plausible ranges; values outside are dropped (warning).
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
    "manual": "own values",
    "orca": "OrcaSlicer",
    "prusa": "PrusaSlicer",
    "ofd": "Open Filament Database",
    "spoolman": "SpoolmanDB",
    "cura": "Cura",
    "derived": "derived",
}


@dataclass
class Issue:
    level: str  # "error" | "warning" | "info"
    message: str
    code: str = ""  # for errors: "diameter" | "base_profile" | "nozzle" | "bed"


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

    def error(self, message: str, code: str = "") -> Generated:
        self.issues.append(Issue("error", message, code))
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
    """The first matching rule wins; if its base profile is missing, nothing is guessed."""
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
        name = material  # product "PLA" with material "PLA+" → "PLA+"
    if family_of(name) is None:
        material = (entry.material or entry.family).strip()
        name = f"{material} {name}".strip() if name.lower() != material.lower() else material
    return clean_name(name.replace("@", " at "))


def filament_id_for(alias: str, user_id: str = "") -> str:
    """Like the Bambu wizard: "P" + 7 characters of the MD5 of the name (and user ID)."""
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
    alias = clean_name(f"{brand} {product}")
    result = Generated(entry=entry, brand=brand, family=entry.family, product=product, alias=alias, name=f"{alias} @{printer}")
    merged = merge(entry)
    result.merged = merged
    for conflict in merged.conflicts:
        others = ", ".join(f"{SOURCE_LABELS.get(s, s)} {v:g}" for s, v in conflict.others.items())
        result.warn(f"{conflict.key}: {SOURCE_LABELS.get(conflict.chosen_source)} {conflict.chosen:g} chosen, differing: {others}")

    if system_keys:
        key = match_key(entry.brand, entry.material or entry.family, entry.name)
        if key in system_keys:
            result.note(f"Bambu Studio already ships the system profile \"{system_keys[key]}\" for it")
            return result
    if brand.lower().replace(" ", "") in {"bambulab", "bambu"}:
        result.note("Bambu Lab filaments have system profiles in Bambu Studio")
        return result

    if merged.diameter is not None and abs(merged.diameter - 1.75) > 0.02:
        return result.error(f"diameter {merged.diameter:g} mm, the printer needs 1.75 mm", "diameter")

    parent = choose_parent(entry.family, entry.tokens, bambu, printer)
    if parent is None:
        return result.error(f"no matching base profile for {entry.family} on \"{printer}\"", "base_profile")
    result.parent = parent
    base = bambu.flatten(parent)
    limits = limits_for(printer)
    values = dict(merged.values)
    provenance = dict(merged.provenance)

    for key, (low, high) in PLAUSIBLE.items():
        if key in values and not (low <= values[key] <= high):
            result.warn(f"{key} = {values[key]:g} implausible, dropped")
            values.pop(key)
    if "filament_max_volumetric_speed" in values:
        mvs = values["filament_max_volumetric_speed"]
        if not (0 < mvs <= limits.volumetric_max):
            result.warn(f"max volumetric speed {mvs:g} mm³/s implausible, dropped")
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
        "description": "",  # filled in below from the values actually used
        "filament_settings_id": [result.name],
        "filament_vendor": [brand],
        "compatible_printers": [printer],
    }
    for key in sorted(values):
        if not key.startswith("_"):
            profile[key] = [fmt(key, values[key])]
    # Only values that made it into the profile count; dropped ones credit no source.
    result.provenance = {k: v for k, v in provenance.items() if k in profile}
    profile["description"] = _description(alias, parent, result.provenance)
    result.profile = profile
    return result


META_KEYS = ("name", "from", "inherits", "version", "description", "filament_settings_id", "filament_vendor", "compatible_printers")


class ExpandError(KeyError):
    pass


def expand(spec: dict, bambu: BambuProfiles, filament_id: str) -> dict:
    """Write a slim profile (inheriting from the Generic profile) out as a standalone one.

    The result matches what the "Create filament" wizard creates: ``inherits``
    empty, all values of the base profile written out, its own
    ``filament_id``. Per-hotend-variant values are repeated to the length of
    the base profile.
    """
    parent = spec.get("inherits") or ""
    try:
        base = bambu.flatten(parent)
    except KeyError as exc:
        raise ExpandError(f"base profile \"{parent}\" is missing in this Bambu Studio version") from exc
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
        result.warn(f"nozzle range {low:g}–{high:g} °C reversed, dropped")
        values.pop("nozzle_temperature_range_low")
        values.pop("nozzle_temperature_range_high")
        low = high = None
    if low is not None and low > limits.nozzle_max:
        result.error(f"needs at least {low:g} °C at the nozzle, the printer reaches {limits.nozzle_max:g} °C", "nozzle")
        return False
    if high is not None and high > limits.nozzle_max:
        result.warn(f"nozzle maximum {high:g} °C capped at {limits.nozzle_max:g} °C")
        values["nozzle_temperature_range_high"] = high = float(limits.nozzle_max)
    for key in ("nozzle_temperature", "nozzle_temperature_initial_layer"):
        if key in values and values[key] > limits.nozzle_max:
            result.error(f"{key} = {values[key]:g} °C above the printer limit {limits.nozzle_max:g} °C", "nozzle")
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
            result.note(f"nozzle temperature {derived:g} °C derived from the range (Generic: {inherited:g} °C)")
    if "nozzle_temperature_initial_layer" not in values and "nozzle_temperature" in values:
        values["nozzle_temperature_initial_layer"] = values["nozzle_temperature"]
        provenance["nozzle_temperature_initial_layer"] = "derived"
    for key in ("nozzle_temperature", "nozzle_temperature_initial_layer"):
        if key in values and not (lo <= values[key] <= hi):
            result.warn(f"{key} = {values[key]:g} °C is outside the manufacturer range")
    if low is None and high is None and "nozzle_temperature" in values:
        base_low = to_number(base.get("nozzle_temperature_range_low"))
        base_high = to_number(base.get("nozzle_temperature_range_high"))
        if base_low is not None and base_high is not None and not (base_low <= values["nozzle_temperature"] <= base_high):
            result.warn(f"nozzle temperature {values['nozzle_temperature']:g} °C is outside the inherited range {base_low:g}–{base_high:g} °C")
    return True


def _bed(result: Generated, values: dict, provenance: dict, base: dict, limits: Limits) -> bool:
    bmin = values.get("_bed_min")
    bmax = values.get("_bed_max")
    if bmin is not None and bmax is not None and bmin > bmax:
        result.warn(f"bed range {bmin:g}–{bmax:g} °C reversed, dropped")
        bmin = bmax = None
    if bmin is not None and bmin > limits.bed_max:
        result.error(f"needs at least {bmin:g} °C on the bed, the printer reaches {limits.bed_max:g} °C", "bed")
        return False
    if bmax is not None and bmax > limits.bed_max:
        # Like the nozzle: a range reaching beyond the printer is usable up to its limit.
        # The range itself is not written to the profile, so no warning is needed.
        bmax = float(limits.bed_max)
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
                result.note(f"{key} {derived:g} °C derived from the bed range (Generic: {inherited:g} °C)")
        if first not in values:
            if "_bed_first" in values:
                values[first] = values["_bed_first"]
                provenance[first] = provenance.get("_bed_first", "derived")
            elif key in values:
                values[first] = values[key]
                provenance[first] = provenance.get(key, "derived")
        for k in (key, first):
            if k in values and values[k] > limits.bed_max:
                result.error(f"{k} = {values[k]:g} °C above the printer limit {limits.bed_max:g} °C", "bed")
                return False
    for plate in OTHER_PLATES:
        for k in (f"{plate}_plate_temp", f"{plate}_plate_temp_initial_layer"):
            if k in values and not (0 <= values[k] <= limits.bed_max):
                result.warn(f"{k} = {values[k]:g} °C dropped (printer limit {limits.bed_max:g} °C)")
                values.pop(k)
    return True


def used_sources(provenance: dict[str, str]) -> list[str]:
    """Labels of the sources whose values are in the profile, in priority order."""
    used = set(provenance.values())
    return [SOURCE_LABELS[s] for s in ("manual", "orca", "prusa", "ofd", "spoolman", "cura") if s in used]


def _description(alias: str, parent: str, provenance: dict) -> str:
    sources = ", ".join(used_sources(provenance)) or "base profile only"
    return f"{MARKER} {__version__}: {alias}. Base {parent}. Values from: {sources}."
