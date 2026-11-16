# bambu-filament-profiles

Filamentprofile für Bambu Studio, **nach Hersteller sortiert** statt alles unter „Generic“.
Das Tool holt offene Filamentdatenbanken **auf deinem Rechner** in ihrem neuesten Stand, erzeugt daraus die
Profile und installiert sie in die lokale Bambu-Studio-Installation (Linux, Flatpak, Windows, macOS).
Im Repo liegen keine fertigen Profile, die veralten könnten.

Zielgerät ist der **Bambu Lab P1S mit 0,4-mm-Düse**.

## Schnellstart

Voraussetzungen: Python 3.11 oder neuer und Git (Windows: `winget install Git.Git`). Weitere Pakete braucht
das Tool nicht.

```bash
git clone https://github.com/skornehl/bambu-filament-profiles.git
cd bambu-filament-profiles
python3 bfp.py app
```

Beim ersten Aufruf holt das Tool die Quellen und erzeugt die Profile (einmalig, rund 15 Sekunden und gut 100 MB).
`app` öffnet dann die Begleit-App im Browser (siehe unten). Dasselbe geht auf der Kommandozeile:

```bash
python3 bfp.py list --vendor SUNLU --material PLA
python3 bfp.py install --vendor SUNLU --material PLA --dry-run
python3 bfp.py install --vendor SUNLU --material PLA
```

Unter Windows heißt der Befehl `py` statt `python3`. Bambu Studio vor dem Installieren oder Löschen schließen.

## Begleit-App

```bash
python3 bfp.py app
```

Startet einen kleinen Server nur auf diesem Rechner (`http://127.0.0.1:8765`) und öffnet die Oberfläche im Browser.
Beenden über den Knopf „Beenden“ oder mit Strg+C.

- **Profile finden:** Suche über Hersteller, Material und Sorte („sunlu matte“), Filter nach Hersteller und Material.
  Ein Klick zeigt die Werte: aus der Quelle oder „geerbt“ vom Basisprofil deiner Bambu-Studio-Version.
  Mehrere anhaken, „Installieren…“ zeigt erst, was neu ist und was schon existiert; vorhandene werden nur
  überschrieben, wenn du sie anhakst.
- **Meine Profile:** deine vorhandenen Filamentprofile mit Art, Hersteller, Drucker und Ablage (lokal oder Cloud),
  filterbar nach „nur unter Generic“ und „nicht für Drucker“. Lokale Profile lassen sich löschen, für Cloud-Profile
  gibt es eine Liste für *Datei → Verwaltung von Batch-Profilen*.
- **Gleiches Sicherheitsnetz wie `install`:** Backup vor jedem Schreiben, nichts schreiben, solange Bambu Studio
  läuft (die App zeigt das oben an), Cloud-Profile nicht lokal löschen.
- **Schutz:** Der Server lauscht nur auf 127.0.0.1, jede Aktion braucht ein Zufalls-Token der Sitzung, und der
  Host-Header wird geprüft. So kann keine fremde Webseite über deinen Browser installieren oder löschen.

- **Profile aktualisieren:** Oben steht, von wann die Profile sind; der Knopf holt die neuesten Quellen und
  erzeugt die Profile neu. In Bambu Studio ändert das nichts.

Optionen: `--port`, `--data-dir`, `--no-browser`.

## Warum bisher alles unter „Generic“ landet

Ein importiertes Benutzerprofil, das von „Generic PLA“ erbt, übernimmt beim Laden dessen
`filament_id` (`GFL99`). Über diese ID ordnet Bambu Studio den Hersteller zu: im AMS, in der
Spulenverwaltung und auf dem Drucker. Ergebnis: „Generic“.

Der Installer legt deshalb **eigenständige Profile** an, genau wie der Assistent „Filament erstellen“
in Bambu Studio: `inherits` leer, alle Werte ausgeschrieben, Hersteller gesetzt, eigene `filament_id`
(„P“ + 7 Zeichen MD5 aus Name und Konto-ID). Die Basiswerte stammen aus den Systemprofilen der
**lokal installierten** Bambu-Studio-Version, passen also immer zur Version.

Im lokalen Katalog liegen die Profile schlank: Sie erben vom passenden Generic-Profil und enthalten nur die Werte
aus den Quellen. Diese Dateien kann man auch direkt importieren, dann erscheinen sie aber wieder unter „Generic“.

## Befehle

| Befehl | Zweck |
|---|---|
| `update` | neueste Quellen holen und die Profile neu erzeugen |
| `list` | Profile anzeigen, filterbar mit `--vendor`, `--material`, `--name` |
| `install` | ausgewählte Profile in Bambu Studio installieren |
| `cleanup` | vorhandene eigene Filamentprofile auflisten und aufräumen |
| `export` | eigenständige Profile in einen Ordner schreiben (für den Import von Hand) |
| `fetch` | nur die Quellen holen (Teil von `update`) |
| `build` | nur die Profile aus den geholten Quellen erzeugen (Teil von `update`) |

Filter sind Teilstrings und lassen sich wiederholen: `--vendor eSUN --vendor SUNLU --material PLA --material PETG`.

### install

```bash
python3 bfp.py install --vendor Elegoo --material PLA --dry-run
```

Sicherheitsnetz:

- **Probelauf** mit `--dry-run`: zeigt, was neu, unverändert oder schon vorhanden ist, und schreibt nichts.
- **Nur mit Auswahl**: ohne `--vendor`/`--material`/`--name` läuft nichts (alle nur mit `--all`).
- **Backup** des kompletten Filament-Ordners als ZIP, bevor etwas geschrieben wird
  (Linux: `~/.local/share/bambu-filament-profiles/backups`, Windows: `%LOCALAPPDATA%\bambu-filament-profiles\backups`).
- **Keine stillen Überschreibungen**: Gibt es ein Profil mit gleichem Namen, fragt das Tool einzeln nach;
  ohne Rückfragemöglichkeit wird es übersprungen, außer mit `--overwrite`.
- **Bambu Studio muss geschlossen sein**: Läuft es, bricht das Tool ab (außer `--force`), denn Bambu Studio
  sieht neue Dateien erst nach einem Neustart und kann sie beim Beenden überschreiben.
- **Mehrere Installationen oder Benutzer**: Das Tool fragt nach; vorausgewählt ist der in Bambu Studio aktive
  Benutzer. Ohne Terminal mit `--data-dir` bzw. `--user` angeben.

Die Profile landen in `<Datenordner>/user/<Konto-ID>/filament/base/`:

| System | Datenordner |
|---|---|
| Linux | `~/.config/BambuStudio` |
| Linux (Flatpak) | `~/.var/app/com.bambulab.BambuStudio/config/BambuStudio` |
| Windows | `%APPDATA%\BambuStudio` |
| macOS | `~/Library/Application Support/BambuStudio` |

### cleanup: vorhandene Profile aufräumen

```bash
python3 bfp.py cleanup --not-for "P1S 0.4"       # Profile, die nur für andere Drucker gelten
python3 bfp.py cleanup --generic                 # alle, die Bambu Studio unter „Generic“ führt
python3 bfp.py cleanup --vendor eSUN --list-file aufraeumen.md
python3 bfp.py cleanup --generic --delete-local --dry-run
```

Die Liste zeigt je Profil, ob es nur lokal oder auch in der Cloud liegt, wovon es erbt, unter welchem
Hersteller Bambu Studio es führt und für welche Drucker es gilt. Den Drucker liest das Tool aus dem Profil,
aus dem Namenszusatz „@Drucker“ oder aus dem Elternprofil der Installation; ist er nicht bestimmbar, wählt
`--not-for` das Profil vorsichtshalber nicht aus. Nur lesende Aufrufe laufen auch, wenn Bambu Studio offen ist.

**Wichtig:** Profile, die mit der Bambu-Cloud synchronisiert sind, lädt Bambu Studio beim nächsten Start
wieder herunter, wenn nur die lokale Datei fehlt. Bambu Studio merkt sich Cloud-Löschungen nur im laufenden
Programm, ein externes Tool kann sie nicht vormerken. Deshalb:

- **Cloud-Profile** in Bambu Studio löschen: *Datei → Verwaltung von Batch-Profilen* (engl. *Batch Preset
  Management*), Profile anhaken, *Löschen*. `--list-file` schreibt dafür eine Liste zum Abhaken.
- **Nur lokale Profile** löscht `--delete-local` selbst (mit Backup, Probelauf und Rückfrage).

Ein sinnvoller Ablauf zum Umsortieren: `cleanup --generic --list-file …`, die Liste in Bambu Studio löschen,
dann `install` für die Hersteller, die du wirklich nutzt.

### Import von Hand

```bash
python3 bfp.py export --vendor Geeetech --material PLA --out ./export
```

In Bambu Studio: *Datei → Importieren → Konfigurationen importieren* und die Dateien aus `./export` wählen.

## Cloud-Synchronisation und Limit

Ist man in Bambu Studio angemeldet, lädt es neue Benutzerprofile beim nächsten Abgleich in die Bambu-Cloud
hoch. Wie viele Filamentprofile die Cloud annimmt, entscheidet der Bambu-Server; die Zahl steht nicht im
Programm. Bambu nannte früher 200 Filamentprofile, Forenberichte zu neueren Versionen 100, manche Konten haben
aber deutlich mehr synchronisiert. Ist das Limit erreicht, meldet Bambu Studio „Die Anzahl der in der Cloud
zwischengespeicherten Profile hat die Obergrenze überschritten. Neu erstellte Profile können nur lokal verwendet
werden.“ Darum installiert das Tool nie alles auf einmal.

## Quellen und Priorität

| Quelle | Lizenz | liefert |
|---|---|---|
| [OrcaSlicer-Filamentbibliothek](https://github.com/OrcaSlicer/OrcaSlicer/tree/main/resources/profiles/OrcaFilamentLibrary) | AGPL-3.0 | vom Hersteller abgestimmte Feinwerte: Temperaturen, Lüfter, Kühlung, Max. Volumenfluss, Fluss, Rückzug |
| [PrusaSlicer-settings, Paket Templates](https://github.com/prusa3d/PrusaSlicer-settings) | AGPL-3.0 | Temperaturen inkl. erster Schicht, Bett, Lüfter, Dichte |
| [Open Filament Database](https://github.com/OpenFilamentCollective/open-filament-database) | MIT | Gerüst Hersteller/Material/Sorte, Herstellerbereiche für Düse und Bett, Dichte |
| [SpoolmanDB](https://github.com/Donkie/SpoolmanDB) | MIT | Stammdaten: Dichte, Temperaturen |
| [Cura fdm_materials](https://github.com/Ultimaker/fdm_materials) | CC0 | Temperaturen, Dichte |
| [Bambu Studio](https://github.com/bambulab/BambuStudio) | AGPL-3.0 | Generic-Basisprofile; vorhandene Systemprofile |

Bei Widersprüchen gewinnt: eigene Werte (`manual/`) → OrcaSlicer → PrusaSlicer → Open Filament Database →
SpoolmanDB → Cura → geerbter Generic-Wert. Ausnahme: Dichte und Temperaturbereiche (Herstellerangaben) nimmt
das Tool zuerst aus der Open Filament Database. Weichen Temperaturen um mehr als 10 °C ab, steht das im Bericht.
Max. Volumenfluss und Flussfaktor aus PrusaSlicer bleiben außen vor, sie gelten für Prusa-Hotends.

Filamente, für die Bambu Studio schon ein Systemprofil mitbringt (Bambu Lab, einige von Polymaker, SUNLU,
Overture, eSUN), erzeugt das Tool nicht.

[3dfilamentprofiles.com](https://3dfilamentprofiles.com) ist **keine** Quelle: Die Nutzungsbedingungen
verbieten automatisierten Abruf und abgeleitete Datensammlungen. Werte, die du dort selbst abliest, kannst du
als eigene Werte eintragen (nur für den privaten Gebrauch).

Lizenzhinweise: [THIRD_PARTY.md](THIRD_PARTY.md).

## Prüfregeln für den P1S

- Düse höchstens 300 °C: Braucht ein Filament mindestens mehr, wird es übersprungen (PEEK, PEI, PPS …).
  Eine höhere Obergrenze wird auf 300 °C begrenzt.
- Bett höchstens 100 °C: Braucht ein Filament mindestens mehr, wird es übersprungen.
- Nur 1,75 mm.
- Max. Volumenfluss über 35 mm³/s, Lüfter außerhalb 0–100 %, Fluss außerhalb 0,7–1,3 und Dichte außerhalb
  0,5–3,5 g/cm³ gelten als unplausibel und werden verworfen.
- Liefert eine Quelle nur einen Temperaturbereich und liegt der geerbte Generic-Wert außerhalb, nimmt das Tool
  die Bereichsmitte (auf 5 °C gerundet) und vermerkt das im Bericht.
- Basisprofil je Material: PLA → Generic PLA (Silk, CF, High Speed eigene), PETG/PET/CPE → Generic PETG,
  ABS, ASA, TPU, PA, PC, PCTG, PP, PE, PVA, HIPS … → das passende Generic-Profil für den P1S. Ohne passendes
  Basisprofil wird das Filament gemeldet statt geraten.

## Eigene Werte

Eine TOML-Datei je Filament in `manual/` hat die höchste Priorität, siehe [manual/README.md](manual/README.md).
Danach `python3 bfp.py update` (oder ohne Netz `python3 bfp.py build`).

## Profile aktualisieren

```bash
python3 bfp.py update            # neueste Quellen holen und Profile neu erzeugen
python3 bfp.py update --pinned   # dieselben Quellen-Stände wie beim letzten Mal
```

Alles landet im Datenordner des Tools, nicht im Repo (Linux: `~/.local/share/bambu-filament-profiles`,
Windows: `%LOCALAPPDATA%\bambu-filament-profiles`):

- `sources/`: die Quell-Repos, flach und nur mit den nötigen Dateien,
- `sources.lock.json`: welche Commits zuletzt geholt wurden,
- `profiles/`: die erzeugten Profile, dazu `INDEX.md` (Übersicht), `REPORT.md` (übersprungene Filamente,
  Warnungen) und `BUILD.json` (Zeitpunkt und Quellen-Stände).

Sind die Profile älter als 30 Tage, weisen `list`, `install` und `export` darauf hin. `update --printer` erzeugt
Profile für ein anderes Bambu-Druckerprofil; die Basisprofil-Regeln sind aber auf den P1S abgestimmt.

## Entwicklung

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest --cov
```
