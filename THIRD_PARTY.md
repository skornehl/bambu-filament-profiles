# Third-party data and licenses

This repo is licensed under [AGPL-3.0-or-later](LICENSE). It contains no generated profiles and no copies of
the source databases: the tool fetches the following sources on the user's computer and builds the profiles
from them. Which commits were fetched is recorded in the data folder in `sources.lock.json` and
`profiles/BUILD.json`.

The only third-party material in the repo is the test data under `tests/fixtures/`: small unmodified excerpts
from the sources, one folder per source. Each file lies at the same path as in the upstream repository.

| Source | License | Copyright | Test data |
|---|---|---|---|
| [OpenFilamentCollective/open-filament-database](https://github.com/OpenFilamentCollective/open-filament-database) | MIT | © 2025 OpenFilamentCollective | `tests/fixtures/ofd/` |
| [Donkie/SpoolmanDB](https://github.com/Donkie/SpoolmanDB) | MIT | © 2024 Donkie | `tests/fixtures/spoolman/` |
| [Ultimaker/fdm_materials](https://github.com/Ultimaker/fdm_materials) | CC0-1.0 | public domain | `tests/fixtures/cura/` |
| [OrcaSlicer/OrcaSlicer](https://github.com/OrcaSlicer/OrcaSlicer) | AGPL-3.0 | © OrcaSlicer contributors | `tests/fixtures/orca/` |
| [bambulab/BambuStudio](https://github.com/bambulab/BambuStudio) | AGPL-3.0 | © Bambu Lab | `tests/fixtures/bambu/` |
| [prusa3d/PrusaSlicer-settings](https://github.com/prusa3d/PrusaSlicer-settings) | AGPL-3.0 | © Prusa Research | `tests/fixtures/prusa/` |

## What this means for this repo

- **AGPL-3.0** (OrcaSlicer, Bambu Studio, PrusaSlicer-settings): the excerpts keep their AGPL-3.0 license,
  which this repo uses as well; the license text is in [LICENSE](LICENSE). The table above names the upstream
  repository each excerpt comes from.
- **MIT** (Open Filament Database, SpoolmanDB): the excerpts keep their MIT license, which is compatible with
  AGPL-3.0. The required copyright and permission notice is reproduced below.
- **CC0-1.0** (Cura): no conditions.
- **Generated profiles**: they are built locally on the user's computer and are neither part of this repo nor
  distributed by it. If you share profiles you built, the licenses of the sources they come from may apply.

This is a cautious assessment, not legal advice.

## MIT license notice

Applies to the excerpts from the Open Filament Database (Copyright © 2025 OpenFilamentCollective) and from
SpoolmanDB (Copyright (c) 2024 Donkie):

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
> documentation files (the "Software"), to deal in the Software without restriction, including without
> limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the
> Software, and to permit persons to whom the Software is furnished to do so, subject to the following
> conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or substantial
> portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED
> TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
> THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF
> CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
> DEALINGS IN THE SOFTWARE.

## Not used

[3dfilamentprofiles.com](https://3dfilamentprofiles.com/terms) forbids automated access, copying the database
and derived data collections in its terms. The tool does not access the site.
