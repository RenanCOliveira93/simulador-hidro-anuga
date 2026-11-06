# Simulador Hidráulico ANUGA — Linux e macOS

Reproducible starter for routing a **user-supplied inflow hydrograph** (or a **prescribed released volume** turned into a hydrograph) over a DEM with ANUGA. It generates time-dependent model output that can be inspected interactively (3D HTML), rendered as an MP4, and overlaid on urban/rural land. The model is intentionally separated from `Jurumirim-Flood_Explorer` (the document-based study).

**First exploratory result:** [docs/RESULTADOS_JURUMIRIM_7007HM3.md](docs/RESULTADOS_JURUMIRIM_7007HM3.md) — 7,007.52 hm³ released over 72 h from Jurumirim, 24 h simulated, with urban/rural overlay for Piraju. It is a hypothetical mass-balance scenario, **not a forecast, not a breach, not validated**.

## Scope and limits

This is a numerical-model runner, not a dam-safety assessment and not a dam-breach predictor. It does not calculate a probability of failure, breach geometry, or breach hydrograph. It routes the hydrograph you provide through the terrain and writes an ANUGA `.sww` result. ANUGA can display the water depth evolving over terrain and export an animation. The generated starter configuration is only a template and must not be interpreted as a Jurumirim forecast.

The same engine can be run for the **UHE Jurumirim, UHE Paranapanema, and UHE Piraju**, with separate terrain, inlet, hydrograph, boundaries, and configuration per modeled reach. The repository does not yet contain validated inputs for those reaches. A cascade must be represented with connected reach models and physically consistent upstream/downstream boundary conditions; running three unrelated configurations does not simulate cascade interaction.

No documents from the original project, PAE, PSB, or restricted material belong in this repository. Do not commit confidential reports, personal data, or large raw datasets. Keep data in `data/` locally; it is ignored by Git.

## Requirements

- Linux or macOS, Python 3.11. **On macOS (Apple Silicon) use conda-forge**: `pip install anuga` tries to compile from source and fails because Apple clang rejects `-fopenmp`. The conda-forge package ships ANUGA 4.1 prebuilt (see Install). Native build instructions for Linux: [ANUGA installation docs](https://anuga.readthedocs.io/en/latest/installing_anuga.html).
- A projected DEM in metres covering the entire reach and urban study area. Use a suitable local CRS (Piraju is commonly handled in SIRGAS 2000 / UTM zone 22S, EPSG:31982); confirm the actual raster CRS and vertical datum before use. The attached 30 m global terrain visualization is useful for orientation, not urban-scale hydraulic resolution.
- `data/inlet.geojson`: a LineString marking where the supplied inflow enters the modeled reach, coordinates in the same projected CRS/units as the DEM.
- `data/hydrograph.csv`: columns `time_seconds,discharge_m3s` with nonnegative values, including recession/tail.

The public PAE map and a 30 m global DEM are not sufficient to resolve streets, buildings, small levees, or a defensible “entire city submerged” result. Obtain surveyed/authoritative terrain, river cross-sections, structures, bathymetry, and calibrated boundary conditions for a decision-grade study.

## Install

ANUGA has compiled components. **macOS and Linux (tested on macOS, Apple Silicon, conda 26.1):**

```bash
conda create -p ./.conda -c conda-forge --override-channels python=3.11 \
    anuga rasterio shapely matplotlib pillow ffmpeg geopandas plotly
./.conda/bin/python -m pip install --no-deps -e .
```

Plain `pip install -e .` also works on Linux if ANUGA's native build dependencies are present; on macOS it fails at the OpenMP compile step (see Requirements). The numerical engine is ANUGA; HEC-RAS desktop is not required. Use `OMP_NUM_THREADS=<n>` with `multiprocessor_mode = 2` in the config to run the solver with OpenMP (about 5× faster than one thread in our test).

## Commands

| Command | Purpose |
|---|---|
| `simulador-dem` | reproject/clip a DEM to a projected CRS in metres (fails on unknown CRS or > 1 % nodata) |
| `simulador-hidrograma` | build `hydrograph.csv` from a released **volume** (triangular or exponential); aborts if mass balance does not close |
| `simulador-hidro` | run ANUGA over the DEM with the hydrograph at the inlet line |
| `simulador-impacto` | area and fraction of urban/rural land reached, per maximum-depth threshold, using the solver's own triangles |
| `simulador-visualizar` | `html3d` (interactive 3D with time slider) or `mp4` (map view with clock) from the `.sww` |
| `simulador-animar` | ANUGA's own depth animation (MP4/GIF) |

No automated tests exist yet; nothing here is described as validated. `cli.py` was fixed to build the mesh from the raster (the original runner called an ANUGA function that does not exist in 4.1).

## Prepare a run

1. Put the DEM in `data/dem.tif` and review its metadata with `gdalinfo` or QGIS. It must use horizontal metres and elevations in metres; do not assume the vertical datum.
2. Create an inlet LineString in `data/inlet.geojson`. It must lie within the DEM, cross the channel, and use the same projected coordinates. A line drawn at the dam is only suitable if it represents the discharge boundary for the chosen model extent.
3. Copy `config.example.toml` to `config.toml`; set the domain resolution, simulation duration, output interval, roughness, and boundary tags for the actual model extent.
4. Supply a defensible hydrograph as `data/hydrograph.csv`. Do not use the synthetic example to represent a real breach. For a prescribed-volume scenario: `simulador-hidrograma --volume-hm3 7007.52 --duration-h 72 --out data/hydrograph.csv`. A volume alone does not define a flow: the emptying time and shape are assumptions you must state and vary.
5. Run:

```bash
simulador-hidro --config config.toml
```

ANUGA writes the simulation output under the configured output directory as `.sww`. View it interactively with `anuga_viewer` or QGIS' temporal mesh tools. To make an MP4 animation from the model output:

```bash
simulador-animar output/exploratory_scenario.sww --output output/flood_depth.mp4
```

MP4 export requires `ffmpeg`; GIF export can use Pillow. The animation shows the solver's time steps, not AI-generated interpolation. Preserve the config, input data provenance, software versions, and model logs with every result.

To model another UHE/reach, create another config file with the matching DEM, inlet line, hydrograph, and reviewed boundary tags, then run the same command against that config. Keep scenarios separate until a hydraulic engineer specifies how upstream releases and downstream levels should be coupled.

## Interpretation

An `.sww` file is not proof by itself. Before making claims about Piraju, document and vary at least: DEM/bathymetry accuracy, breach hydrograph and breach location, downstream boundary conditions, Manning roughness, bridges/culverts/levees, initial river level, reservoir level, and model calibration. Report uncertainty and distinguish “maximum modeled extent for these specified inputs” from “maximum physically possible extent.” To support the total-inundation question, quantify the fraction and area of urban land/buildings inundated across an agreed ensemble of plausible and conservative scenarios, and have a qualified hydraulic engineer review the setup and results.

## Repository contents

- `src/jurumirim_sim/`: CLI, input validation, and ANUGA runner (`cli.py`), volume→hydrograph (`hydrograph.py`), DEM prep (`prepare_dem.py`), urban/rural impact (`impact.py`), 3D/MP4 views (`visualize.py`), ANUGA animation (`animate.py`).
- `scenarios/jurumirim_7007hm3_72h/`: versioned inputs of the first exploratory scenario (config, inlet, hydrograph).
- `docs/RESULTADOS_JURUMIRIM_7007HM3.md` and `docs/resultados/`: results, limits, MP4, peak frame, impact JSON.
- `config.example.toml`: explicit run configuration.
- `data/`: local-only input area; ignored by Git.
- `PROMPT_FOR_CLAUDE.md`: handoff prompt for a second code agent/reviewer.

