"""Reproject and clip a DEM to a projected CRS in metres (what the runner requires)."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject


def prepare(src_path: Path, out_path: Path, bbox: tuple[float, float, float, float], crs: str = "EPSG:31982", res: float = 30.0) -> dict:
    """bbox = (xmin, ymin, xmax, ymax) in the TARGET crs. Bilinear resampling. Returns a small provenance dict."""
    xmin, ymin, xmax, ymax = bbox
    if not (xmax > xmin and ymax > ymin):
        raise ValueError("bbox must be (xmin, ymin, xmax, ymax) with max > min")
    width, height = int(round((xmax - xmin) / res)), int(round((ymax - ymin) / res))
    dst = np.full((height, width), np.nan, dtype="float32")
    transform = from_origin(xmin, ymax, res, res)
    with rasterio.open(src_path) as src:
        if src.crs is None:
            raise ValueError("source DEM has no CRS; refusing to guess")
        reproject(rasterio.band(src, 1), dst, src_transform=src.transform, src_crs=src.crs, dst_transform=transform,
                  dst_crs=crs, resampling=Resampling.bilinear, dst_nodata=np.nan, src_nodata=src.nodata)
        src_crs = str(src.crs)
    nodata_frac = float(np.isnan(dst).mean())
    if nodata_frac > 0.01:
        raise ValueError(f"{nodata_frac:.1%} of the clip is outside the source DEM; enlarge the source or shrink the bbox")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", driver="GTiff", height=height, width=width, count=1, dtype="float32", crs=crs,
                       transform=transform, compress="deflate") as out:
        out.write(dst, 1)
    return {"source": str(src_path), "source_crs": src_crs, "crs": crs, "res_m": res, "bbox": bbox, "shape": (height, width),
            "z_min": float(np.nanmin(dst)), "z_max": float(np.nanmax(dst)), "nodata_fraction": nodata_frac,
            "vertical_datum": "unchanged from source (Copernicus GLO-30 is EGM2008 orthometric); not converted"}


def main() -> None:
    p = argparse.ArgumentParser(description="Reproject/clip a DEM to a projected CRS in metres")
    p.add_argument("src", type=Path)
    p.add_argument("--out", type=Path, default=Path("data/dem.tif"))
    p.add_argument("--bbox", type=float, nargs=4, metavar=("XMIN", "YMIN", "XMAX", "YMAX"), required=True, help="in the target CRS")
    p.add_argument("--crs", default="EPSG:31982")
    p.add_argument("--res", type=float, default=30.0)
    a = p.parse_args()
    info = prepare(a.src, a.out, tuple(a.bbox), a.crs, a.res)
    print(f"{a.out}: {info['shape'][1]}x{info['shape'][0]} @ {info['res_m']} m, z {info['z_min']:.0f}..{info['z_max']:.0f} m")


if __name__ == "__main__":
    main()
