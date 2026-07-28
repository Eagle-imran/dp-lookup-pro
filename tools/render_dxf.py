"""
Render a generated .dxf to a PNG so it can actually be looked at.

Geometry checks confirm a drawing is *correct*; they cannot tell you it is
*readable*. Rendering WORLI 733 is what revealed that the plot metadata block
was printed straight across the plot interior, covering the boundary and both
setback lines — no measurement would have caught that.

Not a substitute for opening the file in AutoCAD, but it catches the common
visual faults: overlapping text, annotations sitting on the geometry, a legend
covering the drawing, layers that render invisible.

Usage:
    uv run python tools/render_dxf.py output/worli_cts_733/plot_G-S_733_worli.dxf
    uv run python tools/render_dxf.py <file.dxf> --zoom      # plot area only
    uv run python tools/render_dxf.py <file.dxf> -o out.png

Requires the dev extra:  uv pip install -e ".[dev]"
"""
import argparse
import os
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render a dp-lookup-pro DXF to PNG.")
    ap.add_argument("dxf", help="path to the .dxf file")
    ap.add_argument("-o", "--out", help="output PNG (default: alongside the DXF)")
    ap.add_argument("--zoom", action="store_true",
                    help="frame the plot boundary instead of the whole sheet")
    ap.add_argument("--dpi", type=int, default=120)
    args = ap.parse_args(argv)

    if not os.path.exists(args.dxf):
        print(f"no such file: {args.dxf}", file=sys.stderr)
        return 1

    try:
        import matplotlib
        matplotlib.use("Agg")
        import ezdxf
        import matplotlib.pyplot as plt
        from ezdxf.addons.drawing import Frontend, RenderContext
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    except ImportError as exc:
        print(f"missing dependency ({exc}). Install with: uv pip install -e \".[dev]\"",
              file=sys.stderr)
        return 1

    doc = ezdxf.readfile(args.dxf)
    msp = doc.modelspace()

    fig = plt.figure(figsize=(18, 13), dpi=args.dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")
    Frontend(RenderContext(doc), MatplotlibBackend(ax)).draw_layout(msp, finalize=not args.zoom)

    if args.zoom:
        pts = [p for e in msp.query("LWPOLYLINE[layer=='C-PLOT-BDY']")
               for p in e.get_points("xy")]
        if pts:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            pad = max(max(xs) - min(xs), max(ys) - min(ys)) * 0.5
            ax.set_xlim(min(xs) - pad, max(xs) + pad)
            ax.set_ylim(min(ys) - pad, max(ys) + pad)
            ax.set_aspect("equal")

    out = args.out or os.path.splitext(args.dxf)[0] + (
        "_zoom.png" if args.zoom else "_render.png")
    fig.savefig(out, dpi=args.dpi, facecolor="white")
    plt.close(fig)
    print(f"rendered -> {out}  ({os.path.getsize(out) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
