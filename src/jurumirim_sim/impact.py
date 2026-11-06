"""Overlay ANUGA results on urban / rural land: area and fraction reached per maximum-depth threshold.

Uses the solver's own triangles (no re-interpolation). Depth thresholds apply to the MAXIMUM depth reached at any output step.
Results are conditional on the DEM, hydrograph and boundary assumptions of the run.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

THRESHOLDS_M = (0.1, 0.5, 1.0, 2.0)


def load_sww(path: Path, x0: float, y0: float) -> dict:
    """Per-triangle geometry (absolute CRS coords) and time series of depth at centroids."""
    from netCDF4 import Dataset

    d = Dataset(path)
    x = np.array(d["x"][:]) + x0 + float(getattr(d, "xllcorner", 0.0))
    y = np.array(d["y"][:]) + y0 + float(getattr(d, "yllcorner", 0.0))
    tri = np.array(d["volumes"][:])
    el = np.array(d["elevation_c"][:])
    el = el if el.ndim == 1 else el[0]
    t = np.array(d["time"][:])
    depth = np.maximum(np.array(d["stage_c"][:]) - el, 0.0)  # (T, ntri)
    return dict(x=x, y=y, tri=tri, t=t, depth=depth, elev=el)


def triangle_union(sww: dict, mask: np.ndarray):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    x, y, tri = sww["x"], sww["y"], sww["tri"]
    return unary_union([Polygon(zip(x[tri[i]], y[tri[i]])) for i in np.flatnonzero(mask)])


def impact(sww_path: Path, x0: float, y0: float, municipios: Path, municipio: str, urban: Path, crs: str = "EPSG:31982") -> dict:
    import geopandas as gpd

    s = load_sww(sww_path, x0, y0)
    maxd = s["depth"].max(axis=0)
    t_peak = s["t"][s["depth"].argmax(axis=0)]
    mun = gpd.read_file(municipios).to_crs(crs)
    mun = mun[mun["nome"].str.lower() == municipio.lower()]
    if mun.empty:
        raise ValueError(f"municipio {municipio!r} not found")
    mun_geom = mun.geometry.union_all()
    urb = gpd.read_file(urban).to_crs(crs).geometry.union_all().intersection(mun_geom)
    rural = mun_geom.difference(urb)
    domain = triangle_union(s, np.ones(len(maxd), bool))
    covered = mun_geom.intersection(domain)
    out = {"sww": str(sww_path), "municipio": municipio, "simulated_hours": float(s["t"][-1] / 3600),
           "areas_km2": {"municipio": mun_geom.area / 1e6, "municipio_dentro_do_dominio": covered.area / 1e6,
                         "urbana": urb.area / 1e6, "rural": rural.area / 1e6},
           "by_threshold": []}
    for thr in THRESHOLDS_M:
        wet = triangle_union(s, maxd > thr)
        row = {"profundidade_max_m_acima_de": thr}
        for name, g in (("urbana", urb), ("rural", rural), ("municipio", mun_geom)):
            a = wet.intersection(g).area / 1e6
            row[name] = {"area_km2": round(a, 3), "fracao": round(a / (g.area / 1e6), 4)}
        out["by_threshold"].append(row)
    # peak timing: is the maximum already reached, or still rising at the end of the run?
    inside = np.array([mun_geom.contains(p) for p in _centroids(s)])
    if inside.any():
        series = s["depth"][:, inside].max(axis=1)
        out["pico_no_municipio"] = {"prof_max_m": float(series.max()), "hora_do_pico": float(s["t"][series.argmax()] / 3600),
                                    "prof_no_ultimo_passo_m": float(series[-1]),
                                    "ainda_subindo_no_fim": bool(series.argmax() == len(series) - 1)}
    out["nota"] = ("Condicional ao DEM (Copernicus 30 m, sem batimetria), ao hidrograma assumido e as bordas transmissivas. "
                   "Area 'urbana' = poligonos IBGE 2019 (todos os tipos) dentro do municipio. Nao e previsao.")
    return out


def _centroids(s: dict):
    from shapely.geometry import Point

    cx, cy = s["x"][s["tri"]].mean(1), s["y"][s["tri"]].mean(1)
    return [Point(a, b) for a, b in zip(cx, cy)]


def main() -> None:
    p = argparse.ArgumentParser(description="Area/fraction of urban and rural land reached, per depth threshold")
    p.add_argument("sww", type=Path)
    p.add_argument("--origin", type=float, nargs=2, required=True, metavar=("X0", "Y0"), help="DEM lower-left corner (CRS metres)")
    p.add_argument("--municipios", type=Path, required=True)
    p.add_argument("--municipio", default="Piraju")
    p.add_argument("--urban", type=Path, required=True)
    p.add_argument("--out", type=Path, default=None)
    a = p.parse_args()
    res = impact(a.sww, *a.origin, a.municipios, a.municipio, a.urban)
    out = a.out or a.sww.with_suffix(".impacto.json")
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    ar = res["areas_km2"]
    print(f"{res['municipio']}: {ar['municipio']:.0f} km² (no dominio {ar['municipio_dentro_do_dominio']:.0f}), urbana {ar['urbana']:.1f} km², rural {ar['rural']:.0f} km²; simulado {res['simulated_hours']:.0f} h")
    for r in res["by_threshold"]:
        print(f"  >{r['profundidade_max_m_acima_de']:>4} m: urbana {r['urbana']['area_km2']:7.2f} km² ({r['urbana']['fracao']:.1%})  rural {r['rural']['area_km2']:8.2f} km² ({r['rural']['fracao']:.1%})")
    if "pico_no_municipio" in res:
        print("  pico:", res["pico_no_municipio"])
    print("->", out)


if __name__ == "__main__":
    main()
