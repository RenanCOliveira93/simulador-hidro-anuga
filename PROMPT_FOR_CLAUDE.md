# Prompt for continuing this project with Claude or Codex

You are improving a Linux-only, reproducible ANUGA 2D shallow-water model starter for studying conditional flood-routing scenarios at UHE Jurumirim, UHE Paranapanema, and UHE Piraju and around Piraju, Brazil. The user expects to see the water move and spread over terrain in a physically based simulation, with a view or exportable animation, not an AI-generated video.

## Non-negotiable scientific scope

- The software routes a supplied inflow hydrograph over a DEM. It does not estimate dam-failure probability or calculate the breach hydrograph/geometry.
- Never call a hypothetical input “the Jurumirim breach hydrograph” unless an authoritative source and engineering validation support it.
- A modeled inundation extent is conditional on DEM, bathymetry, structures, roughness, initial water level, inlet hydrograph, and boundary conditions. Do not claim it proves impossibility for every conceivable event.
- The three UHE/reaches require distinct source data and configurations. Do not imply that three independent runs constitute a coupled cascade model.
- Keep restricted PSB/PAE files, confidential project reports, and all large raw datasets out of Git. Do not upload documents to external services without the user's explicit instruction.
- Target Linux. Do not depend on Windows-only desktop applications.

## Engineering tasks

1. Review the current code and ANUGA's current official documentation before changing solver APIs.
2. Improve geospatial input checks: projected CRS in metres, vertical units/datum, DEM nodata, inlet within extent, and consistent inlet/DEM CRS. Prefer GDAL/Rasterio metadata inspection and explicit failure on unknown CRS rather than guessing.
3. Make boundary conditions configurable by named edge tag, with carefully documented choices and validation that every mesh boundary tag is assigned. The default transmissive condition is only a starter assumption.
4. Add transparent scenario outputs: run metadata, peak depth/velocity rasters if a validated export path exists, inundated area by depth threshold, and comparison against authoritative urban/building footprints. Make output CRS and interpolation method explicit.
5. Add an ensemble runner for documented hydrograph, roughness, terrain, and boundary-condition scenarios. Summarize uncertainty rather than cherry-pick one run.
6. Provide a real-data workflow using public/authorized DEM, river bathymetry/cross-sections, hydraulic structures, reservoir levels, and observed flood marks/flows. Record dataset URLs, dates, licenses, vertical datum, and checksums.
7. Include automated unit/integration tests only after the user asks for testing; do not describe an unrun model as validated.
8. Require review by a qualified hydraulic engineer before any public-safety conclusion.

Before making a scientific claim, list source data, assumptions, calibration/validation evidence, sensitivity results, and limitations. The objective is to determine whether plausible and conservative modeled scenarios inundate all of Piraju's urban area, not to engineer or optimize a breach.

