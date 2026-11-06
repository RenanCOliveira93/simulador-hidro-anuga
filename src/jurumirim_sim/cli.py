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

    output_dir = _resolve(base, output["directory"])
    output_dir.mkdir(parents=True, exist_ok=True)
    label = str(output.get("label", "scenario"))
    domain = anuga.create_domain_from_dem(
        str(dem_path),
        maximum_triangle_area=float(model["maximum_triangle_area_m2"]),
        verbose=True,
    )
    domain.set_name(label)
    domain.set_datadir(str(output_dir))
    domain.set_quantity("friction", float(model["manning_n"]))
    domain.set_quantity("stage", expression="elevation")

    boundary = anuga.Transmissive_boundary(domain)
    domain.set_boundary({tag: boundary for tag in model["boundary_tags"]})
    anuga.Inlet_operator(domain, inlet_geometry, Q=_interpolated_flow(times, flows),
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

