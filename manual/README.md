# Your own values

Each `*.toml` file in this folder describes one filament. Its values take precedence over all sources, for
example from your own calibration or from the manufacturer's data sheet. Brand, material and name match the
file to the right entry (spelling does not matter, "PLA+" = "PLA Plus"); if none matches, a new one is created.

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

Allowed keys: the Bambu Studio names `filament_density`, `nozzle_temperature`,
`nozzle_temperature_initial_layer`, `nozzle_temperature_range_low`, `nozzle_temperature_range_high`,
`hot_plate_temp`, `textured_plate_temp`, `cool_plate_temp`, `eng_plate_temp`, `supertack_plate_temp`
(each also with `_initial_layer`), `fan_min_speed`, `fan_max_speed`, `overhang_fan_speed`,
`additional_cooling_fan_speed`, `close_fan_the_first_x_layers`, `fan_cooling_layer_time`,
`slow_down_layer_time`, `slow_down_min_speed`, `filament_max_volumetric_speed`, `filament_flow_ratio`,
`filament_retraction_length`, `filament_retraction_speed`, `temperature_vitrification`, plus
`_bed` and `_bed_first` (bed for Textured PEI and Smooth PEI) and `_bed_min` / `_bed_max`.

Then run `python3 bfp.py update` (offline: `python3 bfp.py build`).
