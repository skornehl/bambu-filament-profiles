# bambu-filament-profiles

Filament profiles for Bambu Studio, **sorted by brand** instead of everything ending up under "Generic".
The tool fetches open filament databases in their newest state **on your computer**, builds the profiles from
them and installs them into your local Bambu Studio installation (Linux, Flatpak, Windows, macOS).
The repo contains no ready-made profiles that could go stale.

Target printer is the **Bambu Lab P1S with a 0.4 mm nozzle**.

## Quick start

Requirements: Python 3.11 or newer and Git (Windows: `winget install Git.Git`). The tool needs no other
packages.

```bash
git clone https://github.com/skornehl/bambu-filament-profiles.git
cd bambu-filament-profiles
python3 bfp.py app
```

On the first run the tool fetches the sources and builds the profiles (once, about 15 seconds and a bit over
100 MB). `app` then opens the companion app in your browser (see below). The same works on the command line:

```bash
python3 bfp.py list --vendor SUNLU --material PLA
python3 bfp.py install --vendor SUNLU --material PLA --dry-run
python3 bfp.py install --vendor SUNLU --material PLA
```

On Windows the command is `py` instead of `python3`. Close Bambu Studio before installing or deleting.

## Companion app

```bash
python3 bfp.py app
```

Starts a small server on this computer only (`http://127.0.0.1:8765`) and opens the interface in your browser.
Stop it with the "Quit" button or with Ctrl+C.

- **Find profiles:** search across brand, material and product ("sunlu matte"), filter by brand and material.
  A click shows the values: from a source, or "inherited" from the base profile of your Bambu Studio version.
  Tick several, and "Install…" first shows what is new and what already exists; existing ones are only
  overwritten if you tick them.
- **My profiles:** your existing filament profiles with kind, brand, printers and where they are stored (local or
  cloud), filterable by "only under Generic" and "not for printer". Local profiles can be deleted; for cloud
  profiles there is a list for *File → Batch Preset Management*. If a brand appears under several spellings
  ("eSUN 3D" next to Bambu Studio's "eSUN"), *Merge spellings…* brings them together (see below).
- **Update profiles:** the header shows how old the profiles are; the button fetches the newest sources and
  rebuilds the profiles. It changes nothing in Bambu Studio.
- **Same safety net as `install`:** a backup before every write, nothing is written while Bambu Studio is
  running (the app shows that at the top), cloud profiles are never deleted locally.
- **Protection:** the server only listens on 127.0.0.1, every action needs the session's random token, and the
  Host header is checked. So no other web page can install or delete anything through your browser.

Options: `--port`, `--data-dir`, `--no-browser`.

## Why everything ends up under "Generic"

An imported user profile that inherits from "Generic PLA" takes over its `filament_id` (`GFL99`) when it is
loaded. Bambu Studio uses this ID to determine the brand: in the AMS, in spool management and on the printer.
Result: "Generic".

The installer therefore creates **standalone profiles**, exactly like the "Create filament" wizard in Bambu
Studio: `inherits` empty, all values written out, brand set, its own `filament_id` ("P" + 7 characters of the
MD5 of the name and account ID). The base values come from the system profiles of the **locally installed**
Bambu Studio version, so they always match your version.

In the local catalog the profiles are slim: they inherit from the matching Generic profile and only contain the
values from the sources. You can import these files directly too, but then they show up under "Generic" again.

## Commands

| Command | Purpose |
|---|---|
| `update` | fetch the newest sources and rebuild the profiles |
| `list` | show profiles, filterable with `--vendor`, `--material`, `--name` |
| `install` | install selected profiles into Bambu Studio |
| `cleanup` | list and clean up your existing filament profiles |
| `export` | write standalone profiles into a folder (for importing by hand) |
| `app` | open the companion app in the browser |
| `fetch` | only fetch the sources (part of `update`) |
| `build` | only build the profiles from the fetched sources (part of `update`) |

Filters are substrings and can be repeated: `--vendor eSUN --vendor SUNLU --material PLA --material PETG`.

### install

```bash
python3 bfp.py install --vendor Elegoo --material PLA --dry-run
```

Safety net:

- **Dry run** with `--dry-run`: shows what is new, unchanged or already present, and writes nothing.
- **Only with a selection**: without `--vendor`/`--material`/`--name` nothing happens (everything only with `--all`).
- **Backup** of the whole filament folder as a ZIP before anything is written
  (Linux: `~/.local/share/bambu-filament-profiles/backups`, Windows: `%LOCALAPPDATA%\bambu-filament-profiles\backups`).
- **No silent overwrites**: if a profile with the same name exists, the tool asks for each one; when it cannot
  ask, the profile is skipped, unless you pass `--overwrite`. An overwritten profile keeps its cloud link, so
  Bambu Studio updates the cloud copy instead of restoring the old one or creating a duplicate.
- **Bambu Studio must be closed**: if it is running, the tool aborts (unless `--force`), because Bambu Studio
  only sees new files after a restart and may overwrite them when it exits.
- **Several installations or users**: the tool asks; preselected is the user that is active in Bambu Studio.
  Without a terminal, pass `--data-dir` or `--user`.

The profiles go to `<data folder>/user/<account ID>/filament/base/`:

| System | Data folder |
|---|---|
| Linux | `~/.config/BambuStudio` |
| Linux (Flatpak) | `~/.var/app/com.bambulab.BambuStudio/config/BambuStudio` |
| Windows | `%APPDATA%\BambuStudio` |
| macOS | `~/Library/Application Support/BambuStudio` |

### cleanup: tidy up existing profiles

```bash
python3 bfp.py cleanup --not-for "P1S 0.4"       # profiles that only apply to other printers
python3 bfp.py cleanup --generic                 # everything Bambu Studio files under "Generic"
python3 bfp.py cleanup --vendor eSUN --list-file cleanup.md
python3 bfp.py cleanup --generic --delete-local --dry-run
```

For each profile the list shows whether it is local only or also in the cloud, what it inherits from, under
which brand Bambu Studio files it and which printers it applies to. The tool reads the printers from the
profile, from the "@printer" name suffix or from the installation's parent profile; if they cannot be
determined, `--not-for` leaves the profile out to be safe. Read-only calls also work while Bambu Studio is open.

**Important:** profiles synced with the Bambu cloud are downloaded again by Bambu Studio on the next start when
only the local file is gone. Bambu Studio only remembers cloud deletions while it is running; an external tool
cannot queue them. Therefore:

- Delete **cloud profiles** in Bambu Studio: *File → Batch Preset Management*, tick the profiles, *Delete*.
  `--list-file` writes a checklist for that.
- **Local-only profiles** are deleted by `--delete-local` itself (with backup, dry run and confirmation).

A sensible way to re-sort: `cleanup --generic --list-file …`, delete the list in Bambu Studio, then `install`
the brands you actually use.

#### Brands under several spellings

Bambu Studio lists a brand once per spelling, so "eSUN 3D" ends up next to "eSUN", and "Tinmorry" next to
"TINMORRY". `cleanup` lists such brands; `--merge-brands` brings them together:

```bash
python3 bfp.py cleanup --merge-brands --dry-run
python3 bfp.py cleanup --merge-brands --list-file old-spellings.md
```

The spelling kept is the one Bambu Studio uses for its own filaments, otherwise the catalog's, otherwise the one
most of your profiles use (the app lets you pick). Your standalone profiles get the new brand and, if the name
starts with the brand, the new name ("eSUN 3D PETG" → "eSUN PETG"):

- **local profiles** are renamed in place,
- **cloud profiles** get a new copy under the new name (uploaded on the next sync); delete the old ones in
  Bambu Studio with the checklist. Only when the name does not change (or only its upper/lower case), the cloud
  profile is updated in place.

The catalog itself always uses Bambu Studio's spelling for brands Bambu Studio ships filaments for.

### Import by hand

```bash
python3 bfp.py export --vendor Geeetech --material PLA --out ./export
```

In Bambu Studio: *File → Import → Import Configs* and choose the files from `./export`.

## Cloud sync and limit

When you are logged in, Bambu Studio uploads new user profiles to the Bambu cloud on the next sync. How many
filament profiles the cloud accepts is decided by the Bambu server; the number is not in the program. Bambu
used to state 200 filament profiles, forum reports for newer versions say 100, but some accounts have synced
considerably more. Once the limit is reached, Bambu Studio reports that the number of presets cached in the
cloud has exceeded the upper limit and that newly created presets can only be used locally. That is why the
tool never installs everything at once.

## Sources and priority

| Source | License | provides |
|---|---|---|
| [OrcaSlicer filament library](https://github.com/OrcaSlicer/OrcaSlicer/tree/main/resources/profiles/OrcaFilamentLibrary) | AGPL-3.0 | values tuned by the manufacturer: temperatures, fans, cooling, max volumetric speed, flow, retraction |
| [PrusaSlicer-settings, Templates bundle](https://github.com/prusa3d/PrusaSlicer-settings) | AGPL-3.0 | temperatures incl. first layer, bed, fans, density |
| [Open Filament Database](https://github.com/OpenFilamentCollective/open-filament-database) | MIT | brand/material/product skeleton, manufacturer ranges for nozzle and bed, density |
| [SpoolmanDB](https://github.com/Donkie/SpoolmanDB) | MIT | master data: density, temperatures |
| [Cura fdm_materials](https://github.com/Ultimaker/fdm_materials) | CC0 | temperatures, density |
| [Bambu Studio](https://github.com/bambulab/BambuStudio) | AGPL-3.0 | Generic base profiles; existing system profiles |

On conflicts the winner is: your own values (`manual/`) → OrcaSlicer → PrusaSlicer → Open Filament Database →
SpoolmanDB → Cura → inherited Generic value. Exception: density and temperature ranges (manufacturer data) come
from the Open Filament Database first. If temperatures differ by more than 10 °C, the report says so.
Max volumetric speed and flow ratio from PrusaSlicer are left out; they apply to Prusa hotends.

Filaments that already have a system profile in Bambu Studio (Bambu Lab, some from Polymaker, SUNLU, Overture,
eSUN) are not generated.

[3dfilamentprofiles.com](https://3dfilamentprofiles.com) is **not** a source: its terms forbid automated access
and derived data collections. Values you read there yourself can be entered as your own values (for private
use only).

License notes: [THIRD_PARTY.md](THIRD_PARTY.md).

## Checks for the P1S

- Nozzle at most 300 °C: if a filament needs more at minimum, it is skipped (PEEK, PEI, PPS …). A higher upper
  limit is capped at 300 °C.
- Bed at most 100 °C: if a filament needs more at minimum, it is skipped.
- 1.75 mm only.
- Max volumetric speed above 35 mm³/s, fans outside 0–100 %, flow outside 0.7–1.3 and density outside
  0.5–3.5 g/cm³ count as implausible and are dropped.
- If a source only gives a temperature range and the inherited Generic value lies outside it, the tool takes
  the middle of the range (rounded to 5 °C) and notes that in the report.
- Base profile per material: PLA → Generic PLA (Silk, CF, High Speed have their own), PETG/PET/CPE → Generic
  PETG, ABS, ASA, TPU, PA, PC, PCTG, PP, PE, PVA, HIPS … → the matching Generic profile for the P1S. Without a
  matching base profile the filament is reported instead of guessed.

## Your own values

One TOML file per filament in `manual/` has the highest priority, see [manual/README.md](manual/README.md).
Then run `python3 bfp.py update` (or, offline, `python3 bfp.py build`).

## Updating the profiles

```bash
python3 bfp.py update            # fetch the newest sources and rebuild the profiles
python3 bfp.py update --pinned   # the same source commits as last time
```

Everything lives in the tool's data folder, not in the repo (Linux: `~/.local/share/bambu-filament-profiles`,
Windows: `%LOCALAPPDATA%\bambu-filament-profiles`):

- `sources/`: the source repos, shallow and with only the files needed,
- `sources.lock.json`: which commits were fetched last,
- `profiles/`: the generated profiles, plus `INDEX.md` (overview), `REPORT.md` (skipped filaments, warnings)
  and `BUILD.json` (time and source commits).

If the profiles are older than 30 days, `list`, `install` and `export` point that out; a catalog built by an
older version of the tool is rebuilt automatically. Unreadable files in a source are skipped and reported. `update --printer` builds
profiles for another Bambu printer profile; the base profile rules are tuned for the P1S, though.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest --cov
```

## License

Copyright (C) 2026 Sebastian Kornehl

Licensed under the GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later), see
[LICENSE](LICENSE). The test data in `tests/fixtures/` are excerpts from the sources above and keep their own
licenses (AGPL-3.0, MIT, CC0-1.0), see [THIRD_PARTY.md](THIRD_PARTY.md).
