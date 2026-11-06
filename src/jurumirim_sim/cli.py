"""Command line interface."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import tomllib
from pathlib import Path
from typing import Any


def _resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def _read_hydrograph(path: Path) -> tuple[list[float], list[float]]:
    times: list[float] = []
    flows: list[float] = []
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"time_seconds", "discharge_m3s"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("Hydrograph CSV needs columns: time_seconds,discharge_m3s")
        for row_number, row in enumerate(reader, start=2):
            try:
                time_s = float(row["time_seconds"])
                flow = float(row["discharge_m3s"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid numeric hydrograph value on row {row_number}") from exc
            if not math.isfinite(time_s) or not math.isfinite(flow) or time_s < 0 or flow < 0:
                raise ValueError(f"Hydrograph values must be finite and nonnegative (row {row_number})")
            if times and time_s <= times[-1]:
                raise ValueError("Hydrograph times must be strictly increasing")
            times.append(time_s)
            flows.append(flow)
    if len(times) < 2 or times[0] != 0:
        raise ValueError("Hydrograph needs at least two rows and must start at time_seconds=0")
    return times, flows


def _interpolated_flow(times: list[float], flows: list[float]):
    def flow(time_s: float) -> float:
        if time_s < times[0] or time_s > times[-1]:
            return 0.0
        for index in range(1, len(times)):
            if time_s <= times[index]:
                fraction = (time_s - times[index - 1]) / (times[index] - times[index - 1])
                return flows[index - 1] + fraction * (flows[index] - flows[index - 1])
        return flows[-1]

    return flow


def _domain_from_dem(anuga, dem_path: Path, maximum_triangle_area: float):
    """Triangular mesh over the DEM rectangle, elevation sampled bilinearly from the raster.

    Fails explicitly on a geographic/unknown CRS (metres required) and on excessive nodata.
    Returns (domain, (x0, y0)): the mesh uses local coordinates, x0/y0 is the DEM's lower-left corner in the raster CRS.
    """
    import numpy as np
    import rasterio
    from scipy.interpolate import RegularGridInterpolator

    with rasterio.open(dem_path) as src:
        if src.crs is None or not src.crs.is_projected:
            raise ValueError("DEM needs a projected CRS in metres (e.g. EPSG:31982); got " + str(src.crs))
        z = src.read(1, masked=True).astype("float64")
        left, bottom, right, top = src.bounds
        res_x, res_y = src.res
    bad = np.ma.getmaskarray(z) | ~np.isfinite(z.filled(np.nan))
    if bad.mean() > 0.01:
        raise ValueError(f"DEM has {bad.mean():.1%} nodata cells; fill or clip it before running")
    zf = z.filled(np.nan)
    zf[bad] = np.nanmin(zf)
    # raster rows go north->south; interpolator wants ascending axes
    xs = left + res_x * (np.arange(zf.shape[1]) + 0.5) - left
    ys = (top - res_y * (np.arange(zf.shape[0]) + 0.5)) - bottom
    interp = RegularGridInterpolator((ys[::-1], xs), zf[::-1, :], bounds_error=False, fill_value=None)

    width, height = right - left, top - bottom
    domain = anuga.create_domain_from_regions(
        [[0.0, 0.0], [width, 0.0], [width, height], [0.0, height]],
        boundary_tags={"bottom": [0], "right": [1], "top": [2], "left": [3]},
        maximum_triangle_area=maximum_triangle_area,
    )
    domain.set_quantity("elevation", function=lambda x, y: interp(np.column_stack([y, x])))
    return domain, (left, bottom)


def run(config_path: Path) -> Path:
    config_path = config_path.resolve()
    with config_path.open("rb") as stream:
        config: dict[str, Any] = tomllib.load(stream)
    base = config_path.parent
    inputs = config["inputs"]
    model = config["model"]
    output = config["output"]
    dem_path = _resolve(base, inputs["dem"])
    inlet_path = _resolve(base, inputs["inlet_geojson"])
    hydrograph_path = _resolve(base, inputs["hydrograph_csv"])
    for path in (dem_path, inlet_path, hydrograph_path):
        if not path.is_file():
            raise FileNotFoundError(f"Required input not found: {path}")

    times, flows = _read_hydrograph(hydrograph_path)
    if float(model["duration_seconds"]) > times[-1]:
        raise ValueError("Hydrograph must cover the full simulation duration, including recession")
    if float(model["yieldstep_seconds"]) <= 0 or float(model["maximum_triangle_area_m2"]) <= 0:
        raise ValueError("yieldstep_seconds and maximum_triangle_area_m2 must be positive")

    try:
        import anuga
        from shapely.geometry import shape
    except ImportError as exc:
        raise RuntimeError("Install project dependencies and ANUGA before running") from exc

    with inlet_path.open(encoding="utf-8") as stream:
        geojson = json.load(stream)
    if geojson.get("type") == "FeatureCollection":
        features = geojson.get("features", [])
        if len(features) != 1:
            raise ValueError("inlet.geojson must contain exactly one LineString feature")
        inlet_geometry = shape(features[0]["geometry"])
    elif geojson.get("type") == "Feature":
        inlet_geometry = shape(geojson["geometry"])
    else:
        inlet_geometry = shape(geojson)
    if inlet_geometry.geom_type != "LineString" or inlet_geometry.is_empty:
        raise ValueError("The inlet geometry must be a non-empty GeoJSON LineString")
    inlet_line = [list(point) for point in inlet_geometry.coords]

    output_dir = _resolve(base, output["directory"])
    output_dir.mkdir(parents=True, exist_ok=True)
    label = str(output.get("label", "scenario"))
    domain, (x0, y0) = _domain_from_dem(anuga, dem_path, float(model["maximum_triangle_area_m2"]))
    inlet_line = [[x - x0, y - y0] for x, y in inlet_line]  # mesh lives in a local frame anchored at the DEM corner
    if int(model.get("multiprocessor_mode", 1)) == 2:
        domain.set_multiprocessor_mode(2)  # OpenMP; thread count from OMP_NUM_THREADS
    domain.set_name(label)
    domain.set_datadir(str(output_dir))
    domain.set_quantity("friction", float(model["manning_n"]))
    domain.set_quantity("stage", expression="elevation")
    domain.set_collect_max_quantities()

    boundary = anuga.Transmissive_boundary(domain)
    domain.set_boundary({tag: boundary for tag in model["boundary_tags"]})
    anuga.Inlet_operator(domain, inlet_line, Q=_interpolated_flow(times, flows),
                         zero_velocity=True, label="user_supplied_hydrograph")

    duration = float(model["duration_seconds"])
    yieldstep = float(model["yieldstep_seconds"])
    for _ in domain.evolve(yieldstep=yieldstep, finaltime=duration):
        pass

    metadata = {
        "label": label,
        "engine": "ANUGA",
        "dem": str(dem_path),
        "inlet": str(inlet_path),
        "hydrograph": str(hydrograph_path),
        "hydrograph_peak_m3s": max(flows),
        "hydrograph_volume_m3_trapezoidal": sum(
            (times[i + 1] - times[i]) * (flows[i + 1] + flows[i]) / 2
            for i in range(len(times) - 1)
        ),
        "duration_seconds": duration,
        "manning_n": float(model["manning_n"]),
        "maximum_triangle_area_m2": float(model["maximum_triangle_area_m2"]),
        "boundary_condition": "transmissive on configured outer boundary tags",
        "interpretation": "exploratory conditional scenario; not a breach probability or validated forecast",
    }
    metadata_path = output_dir / f"{label}_run_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Route a supplied hydrograph over a DEM using ANUGA")
    parser.add_argument("--config", type=Path, default=Path("config.toml"), help="TOML config path")
    args = parser.parse_args()
    try:
        output = run(args.config)
    except Exception as exc:
        print(f"Run failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(f"Run completed. Review ANUGA .sww output and metadata under: {output}")


if __name__ == "__main__":
    main()

