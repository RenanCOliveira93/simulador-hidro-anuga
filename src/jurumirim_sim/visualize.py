"""Interactive 3D (HTML) and MP4 views of an ANUGA run. The frames are the solver's own output steps, resampled to a grid
for display only (nearest triangle centroid); nothing is interpolated in time.

    simulador-visualizar html3d output/run.sww --dem data/dem.tif --out output/run_3d.html
    simulador-visualizar mp4    output/run.sww --dem data/dem.tif --out output/run.mp4
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np

DAMS = {"UHE Jurumirim": (681083.0, 7432016.0), "UHE Paranapanema": (665349.9, 7434775.0), "UHE Piraju": (665735.1, 7438366.0)}
DISCLAIMER = "Cenario hipotetico de volume liberado - DEM Copernicus 30 m sem batimetria - nao e previsao"


def _grid(sww_path: Path, dem_path: Path, cell: float, every_s: float):
    """Return dict(x, y, z, depth[T,ny,nx], t[T]) on a regular grid in the DEM CRS (rows south->north)."""
    import rasterio
    from netCDF4 import Dataset
    from scipy.spatial import cKDTree

    with rasterio.open(dem_path) as src:
        left, bottom, right, top = src.bounds
        step = max(int(round(cell / src.res[0])), 1)
        z = src.read(1)[::step, ::step][::-1].astype("float64")  # south->north
    ny, nx = z.shape
    xs = left + (np.arange(nx) + 0.5) * cell
    ys = bottom + (np.arange(ny) + 0.5) * cell
    d = Dataset(sww_path)
    tri = np.array(d["volumes"][:])
    x = np.array(d["x"][:]) + left + float(getattr(d, "xllcorner", 0.0))
    y = np.array(d["y"][:]) + bottom + float(getattr(d, "yllcorner", 0.0))
    cxy = np.column_stack([x[tri].mean(1), y[tri].mean(1)])
    gx, gy = np.meshgrid(xs, ys)
    idx = cKDTree(cxy).query(np.column_stack([gx.ravel(), gy.ravel()]))[1]
    t = np.array(d["time"][:])
    el = np.array(d["elevation_c"][:])
    el = el if el.ndim == 1 else el[0]
    keep, last = [], -1e18
    for i, ti in enumerate(t):
        if ti - last >= every_s - 1e-6:
            keep.append(i)
            last = ti
    if keep[-1] != len(t) - 1:
        keep.append(len(t) - 1)
    stage = d["stage_c"]
    depth = np.stack([np.maximum(np.array(stage[i])[idx] - el[idx], 0.0).reshape(ny, nx) for i in keep])
    return dict(xs=xs, ys=ys, z=z, depth=depth, t=t[keep])


def html3d(sww: Path, dem: Path, out: Path, cell: float = 150.0, every_h: float = 1.0, min_depth: float = 0.2, exag: float = 4.0) -> Path:
    import plotly.graph_objects as go

    g = _grid(sww, dem, cell, every_h * 3600)
    xs, ys, z, depth, t = g["xs"], g["ys"], g["z"], g["depth"], g["t"]
    vmax = float(np.percentile(depth[depth > min_depth], 98)) if (depth > min_depth).any() else 1.0

    def water(k):
        dep = depth[k]
        zz = np.where(dep > min_depth, z + dep + 1.0, np.nan)
        return go.Surface(x=xs, y=ys, z=np.round(zz, 1), surfacecolor=np.round(np.where(dep > min_depth, dep, np.nan), 1),
                          colorscale=[[0, "#9ad0f5"], [0.5, "#1f78d1"], [1, "#08306b"]], cmin=0, cmax=vmax,
                          showscale=True, colorbar=dict(title="Prof. (m)", len=0.5), name="agua", hovertemplate="prof %{surfacecolor:.1f} m<extra></extra>")

    terrain = go.Surface(x=xs, y=ys, z=np.round(z, 1), surfacecolor=np.round(z, 0),
                         colorscale=[[0, "#1b5e3b"], [0.3, "#bcd479"], [0.6, "#d9a65f"], [1, "#f5f0ea"]], showscale=False,
                         lighting=dict(ambient=0.55, diffuse=0.9, specular=0.05, roughness=0.9), lightposition=dict(x=-8000, y=8000, z=9000),
                         name="terreno", hovertemplate="cota %{z:.0f} m<extra></extra>")
    markers = go.Scatter3d(x=[v[0] for v in DAMS.values()], y=[v[1] for v in DAMS.values()],
                           z=[float(z[np.abs(ys - v[1]).argmin(), np.abs(xs - v[0]).argmin()]) + 60 for v in DAMS.values()],
                           mode="markers+text", text=list(DAMS), textposition="top center", marker=dict(size=5, color="#d62728"), name="barragens")
    frames = [go.Frame(data=[water(k)], traces=[1], name=f"{t[k] / 3600:.1f}") for k in range(len(t))]
    fig = go.Figure(data=[terrain, water(0), markers], frames=frames)
    steps = [dict(method="animate", label=f"{t[k] / 3600:.0f} h", args=[[f"{t[k] / 3600:.1f}"], dict(mode="immediate", frame=dict(duration=0, redraw=True), transition=dict(duration=0))]) for k in range(len(t))]
    span_x, span_y = xs[-1] - xs[0], ys[-1] - ys[0]
    fig.update_layout(
        title=f"Propagacao da onda — {DISCLAIMER}", margin=dict(l=0, r=0, t=50, b=0), height=760,
        scene=dict(aspectmode="manual", aspectratio=dict(x=1.0, y=span_y / span_x, z=exag * (float(z.max() - z.min())) / span_x),
                   xaxis=dict(title="E (m)", showgrid=False), yaxis=dict(title="N (m)", showgrid=False), zaxis=dict(title="cota (m)"),
                   camera=dict(eye=dict(x=-0.6, y=-1.5, z=1.1))),
        updatemenus=[dict(type="buttons", direction="left", x=0.02, y=0.02, buttons=[
            dict(label="▶ Play", method="animate", args=[None, dict(frame=dict(duration=350, redraw=True), fromcurrent=True, transition=dict(duration=0))]),
            dict(label="⏸ Pause", method="animate", args=[[None], dict(mode="immediate", frame=dict(duration=0, redraw=False))])])],
        sliders=[dict(active=0, steps=steps, x=0.2, len=0.75, currentvalue=dict(prefix="t = "))])
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(out, include_plotlyjs=True, auto_play=False)
    return out


def mp4(sww: Path, dem: Path, out: Path, cell: float = 60.0, every_min: float = 20.0, fps: int = 8, min_depth: float = 0.2,
        urban: Path | None = None, municipios: Path | None = None, municipio: str = "Piraju") -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource, LinearSegmentedColormap

    g = _grid(sww, dem, cell, every_min * 60)
    xs, ys, z, depth, t = g["xs"], g["ys"], g["z"], g["depth"], g["t"]
    ext = (xs[0] - cell / 2, xs[-1] + cell / 2, ys[0] - cell / 2, ys[-1] + cell / 2)
    rgb = LightSource(azdeg=315, altdeg=40).shade(z, cmap=LinearSegmentedColormap.from_list("h", ["#2f6b45", "#9cc277", "#ecdca0", "#c9985a", "#efe9e2"]),
                                                 vert_exag=4, blend_mode="soft")
    vmax = float(np.percentile(depth[depth > min_depth], 98)) if (depth > min_depth).any() else 1.0
    outlines = []
    if urban and municipios:
        import geopandas as gpd

        crs = "EPSG:31982"
        mun = gpd.read_file(municipios).to_crs(crs)
        mun = mun[mun["nome"].str.lower() == municipio.lower()]
        outlines = [(mun.geometry.boundary, "#444", 0.8), (gpd.read_file(urban).to_crs(crs).geometry.boundary, "#ff7a00", 1.0)]
    tmp = Path(tempfile.mkdtemp(prefix="frames_"))
    for k in range(len(t)):
        fig, ax = plt.subplots(figsize=(12.8, 8.6), dpi=100)
        ax.imshow(rgb, extent=ext, origin="lower", interpolation="bilinear")
        dep = np.ma.masked_less(depth[k], min_depth)
        im = ax.imshow(dep, extent=ext, origin="lower", cmap="Blues", vmin=0, vmax=vmax, alpha=0.85, interpolation="nearest")
        for geom, col, lw in outlines:
            geom.plot(ax=ax, color=col, linewidth=lw)
        for name, (px, py) in DAMS.items():
            ax.plot(px, py, "o", color="#d62728", ms=6, mec="white")
            ax.annotate(name, (px, py), xytext=(6, 6), textcoords="offset points", fontsize=9, color="#222",
                        bbox=dict(boxstyle="round,pad=0.15", fc="white", alpha=0.7, lw=0))
        ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3]); ax.set_aspect("equal")
        ax.set_xlabel("E (m, UTM 22S)"); ax.set_ylabel("N (m)")
        wet = float((depth[k] > min_depth).sum()) * (cell / 1000) ** 2
        ax.set_title(f"t = {int(t[k] // 3600):02d} h {int(t[k] % 3600 // 60):02d} min    area molhada ≈ {wet:,.0f} km²", fontsize=14, loc="left")
        fig.colorbar(im, ax=ax, shrink=0.6, label="profundidade (m)")
        fig.text(0.01, 0.005, DISCLAIMER + (" | laranja: area urbanizada IBGE 2019; cinza: limite municipal" if outlines else ""), fontsize=8, color="#555")
        fig.savefig(tmp / f"f{k:04d}.png"); plt.close(fig)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(tmp / "f%04d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", str(out)], check=True)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="3D HTML or MP4 from an ANUGA .sww")
    p.add_argument("kind", choices=["html3d", "mp4"])
    p.add_argument("sww", type=Path)
    p.add_argument("--dem", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--every-min", type=float, default=None, help="time between displayed frames (default 60 for html3d, 20 for mp4)")
    p.add_argument("--cell", type=float, default=None, help="display grid in m (default 150 html3d, 60 mp4)")
    p.add_argument("--urban", type=Path); p.add_argument("--municipios", type=Path); p.add_argument("--municipio", default="Piraju")
    a = p.parse_args()
    if a.kind == "html3d":
        out = html3d(a.sww, a.dem, a.out, cell=a.cell or 150.0, every_h=(a.every_min or 60.0) / 60)
    else:
        out = mp4(a.sww, a.dem, a.out, cell=a.cell or 60.0, every_min=a.every_min or 20.0, urban=a.urban, municipios=a.municipios, municipio=a.municipio)
    print("->", out, f"({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
