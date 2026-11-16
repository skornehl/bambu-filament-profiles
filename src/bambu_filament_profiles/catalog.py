"""Full run: load the sources, match them, generate and write the profiles."""

from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .fetch import fetch_all, read_lock, write_lock
from .generate import DEFAULT_PRINTER, SOURCE_LABELS, Generated, generate
from .merge import build_catalog
from .model import Record
from .sources import cura, manual, ofd, orca, prusa, spoolman
from .sources.bambu import BambuProfiles

LOADERS = {
    "ofd": lambda root, printer: ofd.load(root),
    "orca": orca.load,
    "prusa": lambda root, printer: prusa.load(root),
    "spoolman": lambda root, printer: spoolman.load(root),
    "cura": lambda root, printer: cura.load(root),
}

#: State of the catalog (time, printer, source commits), stored next to the profiles.
BUILD_INFO = "BUILD.json"


@dataclass
class BuildResult:
    generated: list[Generated]
    unmatched: list[Record]
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> list[Generated]:
        return [g for g in self.generated if g.ok]


def load_records(cache_dir: Path, manual_dir: Path | None, printer: str, log=print) -> dict[str, list[Record]]:
    records: dict[str, list[Record]] = {}
    for name, loader in LOADERS.items():
        root = Path(cache_dir) / name
        if not root.is_dir():
            log(f"source {name} is missing in the cache, skipped")
            continue
        records[name] = loader(root, printer)
        log(f"{name}: read {len(records[name])} filaments")
    if manual_dir is not None:
        records["manual"] = manual.load(manual_dir)
    return records


def build(records: dict[str, list[Record]], bambu: BambuProfiles, printer: str = DEFAULT_PRINTER) -> BuildResult:
    catalog = build_catalog(records)
    system_keys = bambu.system_keys(printer)
    generated = [generate(entry, bambu, printer, system_keys) for entry in catalog.entries]
    _dedupe_paths(generated)
    counts = Counter("ok" if g.ok else ("system" if any(i.level == "info" for i in g.issues) and not any(i.level == "error" for i in g.issues) else "error") for g in generated)
    return BuildResult(generated=generated, unmatched=catalog.unmatched, counts=dict(counts))


def _dedupe_paths(generated: list[Generated]) -> None:
    """Duplicate paths or profile names get "(2)", "(3)" … appended."""
    paths: set[str] = set()
    names: set[str] = set()
    for g in generated:
        if not g.ok:
            continue
        base_product = g.product
        counter = 1
        while g.relpath.lower() in paths or g.name.lower() in names:
            counter += 1
            g.product = f"{base_product} ({counter})"
            g.alias = f"{g.brand} {g.product}"
            g.name = f"{g.alias} @{g.profile['compatible_printers'][0]}"
        if counter > 1:
            g.profile["name"] = g.name
            g.profile["filament_settings_id"] = [g.name]
        paths.add(g.relpath.lower())
        names.add(g.name.lower())


def update_profiles(cache_dir: Path, lock_path: Path, manual_dir: Path | None, out_dir: Path, printer: str = DEFAULT_PRINTER, pinned: bool = False, log=print) -> BuildResult:
    """Fetch the sources (newest state, or the lock file's commits with ``pinned``) and rebuild the profiles."""
    lock = fetch_all(Path(cache_dir), read_lock(lock_path), update=not pinned, log=log)
    write_lock(lock_path, lock)
    records = load_records(cache_dir, manual_dir, printer, log=log)
    result = build(records, BambuProfiles(Path(cache_dir) / "bambu"), printer)
    write_output(result, out_dir, lock, printer)
    return result


def read_build_info(profiles_dir: Path) -> dict | None:
    """Content of BUILD.json, or ``None`` if it is missing or broken."""
    try:
        info = json.loads((Path(profiles_dir) / BUILD_INFO).read_text(encoding="utf-8"))
        datetime.fromisoformat(info["built"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return info


def catalog_age_days(info: dict | None, now: datetime | None = None) -> int | None:
    if not info:
        return None
    built = datetime.fromisoformat(info["built"])
    if built.tzinfo is None:
        built = built.replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - built).days


def write_output(result: BuildResult, out_dir: Path, lock: dict, printer: str, now: datetime | None = None) -> None:
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()) and not any((out_dir / n).exists() for n in (BUILD_INFO, "INDEX.md")):
        # The folder is about to be emptied; never empty a folder that is not ours.
        raise ValueError(f"{out_dir} is not empty and holds no generated profiles; please use an empty folder")
    if out_dir.exists():
        for child in out_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            elif child.suffix in {".json", ".md"}:
                child.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)
    for g in result.ok:
        path = out_dir / g.relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(g.profile, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    built = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    info = {"built": built.isoformat(), "printer": printer, "profiles": len(result.ok), "sources": lock}
    (out_dir / BUILD_INFO).write_text(json.dumps(info, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "INDEX.md").write_text(render_index(result, lock, printer), encoding="utf-8")
    (out_dir / "REPORT.md").write_text(render_report(result), encoding="utf-8")


def render_index(result: BuildResult, lock: dict, printer: str) -> str:
    by_brand: dict[str, list[Generated]] = defaultdict(list)
    for g in result.ok:
        by_brand[g.brand].append(g)
    lines = [
        "# Filament profiles",
        "",
        f"For **{printer}**, {len(result.ok)} profiles from {len(by_brand)} brands. "
        "Generated by `bfp update`; do not edit by hand.",
        "",
        "Source commits:",
        "",
    ]
    for name in sorted(lock):
        lines.append(f"- {name}: `{lock[name]['commit'][:12]}` ({lock[name].get('license', '?')})")
    lines += ["", "## Brands", ""]
    lines.append(" · ".join(f"[{b}](#{_anchor(b)})" for b in sorted(by_brand, key=str.lower)))
    for brand in sorted(by_brand, key=str.lower):
        lines += ["", f"## {brand}", "", "| Material | Product | Base profile | Values from | File |", "|---|---|---|---|---|"]
        for g in sorted(by_brand[brand], key=lambda x: (x.family, x.product.lower())):
            sources = ", ".join(SOURCE_LABELS[s] for s in sorted(set(g.provenance.values()), key=list(SOURCE_LABELS).index))
            lines.append(f"| {g.family} | {g.product} | {g.parent} | {sources or 'base profile'} | [{g.relpath.split('/')[-1]}]({_link(g.relpath)}) |")
    return "\n".join(lines) + "\n"


def render_report(result: BuildResult) -> str:
    errors = [g for g in result.generated if any(i.level == "error" for i in g.issues)]
    system = [g for g in result.generated if not g.ok and not any(i.level == "error" for i in g.issues)]
    warned = [g for g in result.ok if any(i.level == "warning" for i in g.issues)]
    derived = [g for g in result.ok if any(i.level == "info" for i in g.issues)]
    lines = [
        "# Report of the last run",
        "",
        f"- generated: {len(result.ok)}",
        f"- skipped because Bambu Studio already has a system profile: {len(system)}",
        f"- skipped because of errors: {len(errors)}",
        f"- generated with warnings: {len(warned)}",
        f"- generated with derived values: {len(derived)}",
        f"- no recognisable material (unmatched): {len(result.unmatched)}",
    ]
    reasons = Counter(_reason(i.message) for g in errors for i in g.issues if i.level == "error")
    if reasons:
        lines += ["", "## Error reasons", ""] + [f"- {r}: {n}" for r, n in reasons.most_common()]
    sections = (
        ("Skipped (errors)", errors, "error"),
        ("System profile exists", system, "info"),
        ("Warnings", warned, "warning"),
        ("Derived values", derived, "info"),
    )
    for title, items, level in sections:
        if not items:
            continue
        lines += ["", f"## {title}", ""]
        for g in sorted(items, key=lambda x: x.alias.lower()):
            messages = "; ".join(i.message for i in g.issues if i.level == level)
            lines.append(f"- **{g.alias}** ({', '.join(sorted(set(g.entry.sources)))}): {messages}")
    if result.unmatched:
        lines += ["", "## Unmatched", ""]
        for r in sorted(result.unmatched, key=lambda x: (x.source, x.brand.lower(), x.name.lower())):
            lines.append(f"- {r.source}: {r.brand} {r.name} (material \"{r.material}\")")
    return "\n".join(lines) + "\n"


def _reason(message: str) -> str:
    if "base profile" in message:
        return "no matching base profile"
    if "nozzle" in message:
        return "too hot for the nozzle"
    if "bed" in message or "plate" in message:
        return "too hot for the bed"
    if "diameter" in message:
        return "wrong diameter"
    return message


def _anchor(text: str) -> str:
    return "".join(c for c in text.lower().replace(" ", "-") if c.isalnum() or c == "-")


def _link(relpath: str) -> str:
    return relpath.replace(" ", "%20")


def list_profiles(profiles_dir: Path) -> list[dict]:
    """All stored profiles with brand, material and product (for install/list)."""
    items = []
    for path in sorted(Path(profiles_dir).glob("*/*/*.json")):
        items.append({"brand": path.parent.parent.name, "material": path.parent.name, "product": path.stem, "path": path})
    return items


def select_profiles(items: list[dict], vendors=(), materials=(), names=()) -> list[dict]:
    def hit(value: str, needles) -> bool:
        return not needles or any(n.lower() in value.lower() for n in needles)

    def material_hit(value: str) -> bool:
        return not materials or any(m.lower() == value.lower() for m in materials)

    return [i for i in items if hit(i["brand"], vendors) and material_hit(i["material"]) and hit(i["product"], names)]
