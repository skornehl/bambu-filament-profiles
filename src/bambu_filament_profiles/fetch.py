"""Clone the source repos shallow and sparse into a cache.

``fetch`` gets the newest state and records the commits in
``sources.lock.json`` in this tool's data folder; ``fetch --pinned`` gets
exactly those commits again. Neither sources nor generated profiles live in
the repo.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    license: str
    patterns: tuple[str, ...]
    description: str


SOURCES: dict[str, Source] = {
    s.name: s
    for s in (
        Source(
            "bambu",
            "https://github.com/bambulab/BambuStudio.git",
            "AGPL-3.0",
            ("/resources/profiles/BBL.json", "/resources/profiles/BBL/filament/**", "/LICENSE"),
            "Bambu Studio: Generic base profiles and system profiles",
        ),
        Source(
            "orca",
            "https://github.com/OrcaSlicer/OrcaSlicer.git",
            "AGPL-3.0",
            ("/resources/profiles/OrcaFilamentLibrary/filament/**", "/LICENSE.txt"),
            "OrcaSlicer filament library: manufacturer profiles with tuned values",
        ),
        Source(
            "ofd",
            "https://github.com/OpenFilamentCollective/open-filament-database.git",
            "MIT",
            (
                "/data/*/brand.json",
                "/data/*/*/material.json",
                "/data/*/*/*/filament.json",
                "/data/*/*/*/*/sizes.json",
                "/LICENSE",
            ),
            "Open Filament Database: brands, products, temperature ranges",
        ),
        Source(
            "prusa",
            "https://github.com/prusa3d/PrusaSlicer-settings.git",
            "AGPL-3.0",
            ("/live/Templates/*.ini", "/License"),
            "PrusaSlicer templates: temperatures, fans, density",
        ),
        Source(
            "spoolman",
            "https://github.com/Donkie/SpoolmanDB.git",
            "MIT",
            ("/filaments/*.json", "/LICENSE"),
            "SpoolmanDB: master data",
        ),
        Source(
            "cura",
            "https://github.com/Ultimaker/fdm_materials.git",
            "CC0-1.0",
            ("/*.xml.fdm_material", "/LICENSE"),
            "Cura fdm_materials: temperatures, density",
        ),
    )
}


class FetchError(RuntimeError):
    pass


def _git(args: list[str], cwd: Path, run=subprocess.run) -> str:
    try:
        proc = run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise FetchError("git not found. Please install Git (Windows: winget install Git.Git)") from exc
    if proc.returncode != 0:
        raise FetchError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def read_lock(path: Path) -> dict:
    if not Path(path).exists():
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_lock(path: Path, lock: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fetch_source(source: Source, cache_dir: Path, ref: str, run=subprocess.run) -> str:
    """Bring the source to ``ref`` (commit or ``HEAD``) and return the commit."""
    target = Path(cache_dir) / source.name
    target.mkdir(parents=True, exist_ok=True)
    if not (target / ".git").exists():
        _git(["init", "-q"], target, run)
        _git(["remote", "add", "origin", source.url], target, run)
        _git(["config", "core.sparseCheckout", "true"], target, run)
    else:
        _git(["remote", "set-url", "origin", source.url], target, run)
    _git(["sparse-checkout", "set", "--no-cone", *source.patterns], target, run)
    _git(["fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", ref], target, run)
    _git(["checkout", "-q", "--detach", "FETCH_HEAD"], target, run)
    return _git(["rev-parse", "HEAD"], target, run)


def fetch_all(cache_dir: Path, lock: dict, update: bool = False, names=None, run=subprocess.run, log=print) -> dict:
    new_lock = dict(lock)
    for name, source in SOURCES.items():
        if names and name not in names:
            continue
        ref = "HEAD" if update or name not in lock else lock[name]["commit"]
        log(f"{name}: {source.url} @ {ref[:12]}")
        commit = fetch_source(source, cache_dir, ref, run)
        new_lock[name] = {"url": source.url, "commit": commit, "license": source.license}
    return new_lock
