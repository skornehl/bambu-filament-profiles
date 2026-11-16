# Eigene Werte

Jede `*.toml`-Datei in diesem Ordner beschreibt ein Filament. Ihre Werte haben Vorrang vor allen Quellen,
etwa aus eigener Kalibrierung oder vom Datenblatt des Herstellers. Hersteller, Material und Name ordnen die
Datei dem passenden Eintrag zu (Schreibweise egal, „PLA+“ = „PLA Plus“); passt keiner, entsteht ein neuer.

```toml
brand = "Geeetech"
material = "PLA"
name = "PLA"
# diameter = 1.75

[values]
nozzle_temperature = 205
nozzle_temperature_initial_layer = 210
filament_flow_ratio = 0.98
filament_max_volumetric_speed = 18
fan_min_speed = 100
```

Erlaubte Schlüssel: die Bambu-Studio-Namen `filament_density`, `nozzle_temperature`,
`nozzle_temperature_initial_layer`, `nozzle_temperature_range_low`, `nozzle_temperature_range_high`,
`hot_plate_temp`, `textured_plate_temp`, `cool_plate_temp`, `eng_plate_temp`, `supertack_plate_temp`
(jeweils auch mit `_initial_layer`), `fan_min_speed`, `fan_max_speed`, `overhang_fan_speed`,
`additional_cooling_fan_speed`, `close_fan_the_first_x_layers`, `fan_cooling_layer_time`,
`slow_down_layer_time`, `slow_down_min_speed`, `filament_max_volumetric_speed`, `filament_flow_ratio`,
`filament_retraction_length`, `filament_retraction_speed`, `temperature_vitrification` sowie
`_bed` und `_bed_first` (Bett für Textured PEI und Smooth PEI) und `_bed_min` / `_bed_max`.

Danach `python bfp.py build` ausführen.
