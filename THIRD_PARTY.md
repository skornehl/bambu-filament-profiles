# Third-party data and licenses

The tool fetches the following sources on the user's computer and builds the profiles from them; the repo
contains no generated profiles. Which commits were fetched is recorded in the data folder in
`sources.lock.json` and `profiles/BUILD.json`. The test data under `tests/fixtures/` are small unmodified
excerpts from the sources.

| Source | License | Copyright |
|---|---|---|
| [OpenFilamentCollective/open-filament-database](https://github.com/OpenFilamentCollective/open-filament-database) | MIT | © 2025 OpenFilamentCollective |
| [Donkie/SpoolmanDB](https://github.com/Donkie/SpoolmanDB) | MIT | © 2024 Donkie |
| [Ultimaker/fdm_materials](https://github.com/Ultimaker/fdm_materials) | CC0-1.0 | public domain |
| [OrcaSlicer/OrcaSlicer](https://github.com/OrcaSlicer/OrcaSlicer) | AGPL-3.0 | © OrcaSlicer contributors |
| [bambulab/BambuStudio](https://github.com/bambulab/BambuStudio) | AGPL-3.0 | © Bambu Lab |
| [prusa3d/PrusaSlicer-settings](https://github.com/prusa3d/PrusaSlicer-settings) | AGPL-3.0 | © Prusa Research |

## What this means for this repo

- **MIT** (Open Filament Database, SpoolmanDB): free use and redistribution; when redistributing, include the
  copyright and license notice (this file).
- **CC0** (Cura): no conditions.
- **AGPL-3.0** (OrcaSlicer, Bambu Studio, PrusaSlicer-settings): obligations only arise on redistribution.
  The generated profiles are created locally and are not redistributed. In the repo this only concerns the test
  data: if the repo is published, they should be under AGPL-3.0 with a source notice.

This is a cautious assessment, not legal advice.

## Not used

[3dfilamentprofiles.com](https://3dfilamentprofiles.com/terms) forbids automated access, copying the database
and derived data collections in its terms. The tool does not access the site.
