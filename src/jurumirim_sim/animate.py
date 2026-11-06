"""Render a time-dependent ANUGA depth result as a movie or GIF."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render water-depth frames from an ANUGA .sww result"
    )
    parser.add_argument("sww", type=Path, help="ANUGA .sww simulation output")
    parser.add_argument("--output", type=Path, required=True, help="Output .mp4 or .gif path")
    parser.add_argument("--fps", type=int, default=5, help="Animation playback frames per second")
    parser.add_argument("--min-depth", type=float, default=0.05,
                        help="Hide depths below this value in metres (default: 0.05)")
    args = parser.parse_args()
    if not args.sww.is_file():
        parser.error(f"SWW file not found: {args.sww}")
    if args.fps <= 0 or args.min_depth < 0:
        parser.error("fps must be positive and min-depth must be nonnegative")
    suffix = args.output.suffix.lower()
    if suffix not in {".mp4", ".gif"}:
        parser.error("output extension must be .mp4 or .gif")

    try:
        import anuga
    except ImportError as exc:
        print("ANUGA is required; install this project first.", file=sys.stderr)
        raise SystemExit(2) from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    plotter = anuga.SWW_plotter(str(args.sww), min_depth=args.min_depth)
    animation = plotter.make_depth_animation()
    writer = "ffmpeg" if suffix == ".mp4" else "pillow"
    try:
        animation.save(str(args.output), writer=writer, fps=args.fps)
    except (RuntimeError, FileNotFoundError) as exc:
        if writer == "ffmpeg":
            print("MP4 export needs ffmpeg installed and on PATH; try .gif or install ffmpeg.",
                  file=sys.stderr)
        raise SystemExit(2) from exc
    print(f"Animation saved: {args.output}")


if __name__ == "__main__":
    main()
