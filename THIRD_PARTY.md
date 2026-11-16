# Fremde Daten und Lizenzen

Das Tool holt die folgenden Quellen auf dem Rechner des Benutzers und erzeugt daraus die Profile; das Repo
enthält keine erzeugten Profile. Welche Stände geholt wurden, steht im Datenordner in `sources.lock.json` und
`profiles/BUILD.json`. Die Testdaten unter `tests/fixtures/` sind kleine unveränderte Auszüge aus den Quellen.

| Quelle | Lizenz | Copyright |
|---|---|---|
| [OpenFilamentCollective/open-filament-database](https://github.com/OpenFilamentCollective/open-filament-database) | MIT | © 2025 OpenFilamentCollective |
| [Donkie/SpoolmanDB](https://github.com/Donkie/SpoolmanDB) | MIT | © 2024 Donkie |
| [Ultimaker/fdm_materials](https://github.com/Ultimaker/fdm_materials) | CC0-1.0 | gemeinfrei |
| [OrcaSlicer/OrcaSlicer](https://github.com/OrcaSlicer/OrcaSlicer) | AGPL-3.0 | © OrcaSlicer-Mitwirkende |
| [bambulab/BambuStudio](https://github.com/bambulab/BambuStudio) | AGPL-3.0 | © Bambu Lab |
| [prusa3d/PrusaSlicer-settings](https://github.com/prusa3d/PrusaSlicer-settings) | AGPL-3.0 | © Prusa Research |

## Was das für dieses Repo heißt

- **MIT** (Open Filament Database, SpoolmanDB): freie Nutzung und Weitergabe; bei Weitergabe den
  Copyright- und Lizenzhinweis beilegen (diese Datei).
- **CC0** (Cura): keine Bedingungen.
- **AGPL-3.0** (OrcaSlicer, Bambu Studio, PrusaSlicer-settings): Pflichten entstehen erst bei Weitergabe.
  Die erzeugten Profile entstehen lokal und werden nicht weitergegeben. Im Repo betrifft das nur die Testdaten:
  Wird es veröffentlicht, sollten sie unter AGPL-3.0 mit Quellenhinweis stehen.

Das ist eine vorsichtige Einschätzung, keine Rechtsberatung.

## Nicht verwendet

[3dfilamentprofiles.com](https://3dfilamentprofiles.com/terms) verbietet in den Nutzungsbedingungen
automatisierten Abruf, das Kopieren der Datenbank und abgeleitete Datensammlungen. Das Tool ruft die Seite
nicht ab.
