"""Generate an inflow hydrograph from a prescribed released VOLUME (mass-balance scenario).

This does not model a breach: it answers "if V cubic metres were released over this time, with this shape,
where would the water go?". The volume is an input assumption, not a prediction. Because a volume alone does not
define a flow, the emptying time (and shape) must be chosen explicitly; vary it in an ensemble.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

HM3 = 1e6  # m³ per hm³


def _trapezoid_volume(t: list[float], q: list[float]) -> float:
    return sum((t[i + 1] - t[i]) * (q[i + 1] + q[i]) / 2 for i in range(len(t) - 1))


def triangular(volume_m3: float, duration_s: float, peak_time_s: float, dt_s: float) -> tuple[list[float], list[float]]:
    """Linear rise to the peak at peak_time_s, linear fall to zero at duration_s. Peak = 2V/duration (exact)."""
    if not 0 < peak_time_s < duration_s:
        raise ValueError("peak_time must be inside (0, duration)")
    qp = 2.0 * volume_m3 / duration_s
    times = sorted({0.0, peak_time_s, duration_s, *(k * dt_s for k in range(1, int(duration_s // dt_s) + 1) if k * dt_s < duration_s)})
    flows = [qp * t / peak_time_s if t <= peak_time_s else qp * (duration_s - t) / (duration_s - peak_time_s) for t in times]
    return times, flows


def exponential(volume_m3: float, duration_s: float, tau_s: float, dt_s: float) -> tuple[list[float], list[float]]:
    """Instant-peak exponential recession Q0*exp(-t/tau), truncated at duration_s and rescaled so the volume is exact."""
    if tau_s <= 0:
        raise ValueError("tau must be positive")
    n = max(int(duration_s // dt_s), 1)
    times = [min(k * dt_s, duration_s) for k in range(n + 1)]
    if times[-1] < duration_s:
        times.append(duration_s)
    raw = [math.exp(-t / tau_s) for t in times]
    scale = volume_m3 / _trapezoid_volume(times, raw)
    return times, [scale * v for v in raw]


def with_zero_tail(times: list[float], flows: list[float], total_s: float) -> tuple[list[float], list[float]]:
    """The runner requires the hydrograph to cover the whole simulation; append a zero-flow tail."""
    if total_s > times[-1]:
        return times + [times[-1] + 1e-3, total_s], flows + [0.0, 0.0]
    return times, flows


def write(path: Path, times: list[float], flows: list[float], meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time_seconds", "discharge_m3s"])
        writer.writerows((f"{t:.3f}", f"{q:.6f}") for t, q in zip(times, flows))
    path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description="Build hydrograph.csv from a released volume (conservation-checked)")
    vol = p.add_mutually_exclusive_group(required=True)
    vol.add_argument("--volume-hm3", type=float, help="released volume in hm³ (1 hm³ = 1e6 m³)")
    vol.add_argument("--volume-m3", type=float, help="released volume in m³")
    p.add_argument("--shape", choices=["triangular", "exponential"], default="triangular")
    p.add_argument("--duration-h", type=float, required=True, help="emptying time (hydrograph base), hours")
    p.add_argument("--peak-time-h", type=float, default=None, help="triangular: time of peak, hours (default 10%% of duration)")
    p.add_argument("--tau-h", type=float, default=None, help="exponential: decay constant, hours (default duration/4)")
    p.add_argument("--total-h", type=float, default=None, help="pad with zero flow up to this simulation length, hours")
    p.add_argument("--dt-s", type=float, default=300.0)
    p.add_argument("--out", type=Path, default=Path("data/hydrograph.csv"))
    a = p.parse_args()

    volume = a.volume_m3 if a.volume_m3 is not None else a.volume_hm3 * HM3
    if not math.isfinite(volume) or volume <= 0:
        sys.exit("volume must be positive")
    duration = a.duration_h * 3600
    try:
        if a.shape == "triangular":
            t, q = triangular(volume, duration, (a.peak_time_h * 3600 if a.peak_time_h else 0.1 * duration), a.dt_s)
        else:
            t, q = exponential(volume, duration, (a.tau_h if a.tau_h else a.duration_h / 4) * 3600, a.dt_s)
    except ValueError as exc:
        sys.exit(str(exc))
    if a.total_h:
        t, q = with_zero_tail(t, q, a.total_h * 3600)
    got = _trapezoid_volume(t, q)
    err = abs(got - volume) / volume
    if err > 1e-6:
        sys.exit(f"mass balance failed: target {volume:.6g} m³, got {got:.6g} m³ (rel. error {err:.2e})")
    meta = {"shape": a.shape, "target_volume_m3": volume, "hydrograph_volume_m3": got, "relative_error": err,
            "peak_m3s": max(q), "emptying_time_h": a.duration_h, "mean_m3s": volume / duration,
            "note": "Prescribed-volume scenario; not a breach hydrograph nor a prediction."}
    write(a.out, t, q, meta)
    print(f"{a.out}: V={got:.6g} m³ (erro {err:.1e}), pico={max(q):,.0f} m³/s, média={volume / duration:,.0f} m³/s")


if __name__ == "__main__":
    main()
