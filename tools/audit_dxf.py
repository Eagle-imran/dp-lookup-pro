"""
Audit a generated .dxf for the faults that geometry checks cannot see.

Correct coordinates do not make a readable drawing. Every fault found when
WORLI 733 was first opened in AutoCAD - legend rows escaping their panel, the UTM
tie-in lying across a dimension, two grid labels stacked at the sheet corner - was
invisible to coordinate checks, because whether text collides depends on the
rendered width of a glyph, not on where its insertion point sits.

This measures text through ezdxf's font engine and reports:
  * text escaping the sheet border or a panel frame
  * text colliding with other text
  * annotation oversized relative to the plot (the small-plot fault)
  * declared-but-empty layers
  * boundary area vs the area printed on the sheet
  * layers with no lineweight, which plot flat

Usage:
    uv run python tools/audit_dxf.py output/worli_cts_733/plot_G-S_733_worli.dxf
    uv run python tools/audit_dxf.py <file.dxf> --quiet   # exit code only

Exit code is 1 when any fault is found, so CI can gate on it.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def polygon_area(pts):
    n = len(pts)
    s = 0.0
    for i in range(n):
        x1, y1 = pts[i][0], pts[i][1]
        x2, y2 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def entity_text(e):
    return e.plain_text() if hasattr(e, "plain_text") else e.dxf.text


def main(argv=None):
    ap = argparse.ArgumentParser(description="Audit a dp-lookup-pro DXF.")
    ap.add_argument("dxf")
    ap.add_argument("--quiet", action="store_true", help="suppress the report, set exit code only")
    args = ap.parse_args(argv)

    if not os.path.exists(args.dxf):
        print(f"no such file: {args.dxf}", file=sys.stderr)
        return 2

    try:
        import ezdxf
    except ImportError:
        print('ezdxf missing. Install with: uv pip install -e ".[dev]"', file=sys.stderr)
        return 2

    from cts_dp_lookup_pro import boxes_overlap, text_extents

    doc = ezdxf.readfile(args.dxf)
    msp = doc.modelspace()
    faults = []
    out = None if args.quiet else []

    def say(line):
        if out is not None:
            out.append(line)

    # ---- frames -----------------------------------------------------------
    # The sheet border is the largest C-TITLE-BLOCK rectangle; panels are the rest.
    rects = []
    for e in msp:
        if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "C-TITLE-BLOCK":
            pts = e.get_points("xy")
            if len(pts) == 4:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                rects.append((min(xs), min(ys), max(xs), max(ys)))
    rects.sort(key=lambda r: (r[2] - r[0]) * (r[3] - r[1]), reverse=True)
    sheet = rects[0] if rects else None
    panels = rects[1:]

    say("=== frames ===")
    if sheet:
        say(f"  sheet border   x[{sheet[0]:9.2f},{sheet[2]:9.2f}] y[{sheet[1]:9.2f},{sheet[3]:9.2f}]")
    for i, p in enumerate(panels, 1):
        say(f"  panel {i}        x[{p[0]:9.2f},{p[2]:9.2f}] y[{p[1]:9.2f},{p[3]:9.2f}]")

    texts = [(e, text_extents(e)) for e in msp.query("TEXT")]
    texts = [(e, b) for e, b in texts if b]

    say("\n=== text escaping the sheet border ===")
    if sheet:
        escapes = 0
        for e, b in texts:
            over = max(b[2] - sheet[2], sheet[0] - b[0], b[3] - sheet[3], sheet[1] - b[1])
            if over > 0.01:
                escapes += 1
                faults.append(f"text outside sheet border by {over:.2f}: {entity_text(e)[:46]!r}")
                say(f"  +{over:6.2f}  [{e.dxf.layer}] {entity_text(e)[:52]!r}")
        if not escapes:
            say("  none")

    say("\n=== text escaping a panel frame ===")
    # Only judge text that starts inside a panel; drawing-area text is not its problem.
    panel_escapes = 0
    for e, b in texts:
        for p in panels:
            starts_inside = p[0] - 0.01 <= b[0] <= p[2] + 0.01 and p[1] - 40 <= b[1] <= p[3] + 0.01
            if not starts_inside:
                continue
            over_r, under_b = b[2] - p[2], p[1] - b[1]
            if over_r > 0.01 or under_b > 0.01:
                panel_escapes += 1
                flags = []
                if over_r > 0.01:
                    flags.append(f"RIGHT +{over_r:5.2f}")
                if under_b > 0.01:
                    flags.append(f"BELOW +{under_b:5.2f}")
                faults.append(f"panel overrun ({' '.join(flags)}): {entity_text(e)[:46]!r}")
                say(f"  {' '.join(flags):26s} {entity_text(e)[:52]!r}")
            break
    if not panel_escapes:
        say("  none")

    say("\n=== text-on-text collisions ===")
    inside_panel = set()
    for i, (_e, b) in enumerate(texts):
        for p in panels:
            if p[0] - 0.01 <= b[0] <= p[2] + 0.01:
                inside_panel.add(i)
                break
    drawing = [(i, e, b) for i, (e, b) in enumerate(texts) if i not in inside_panel]
    collisions = 0
    for idx, (_i, e1, b1) in enumerate(drawing):
        for _j, e2, b2 in drawing[idx + 1:]:
            if boxes_overlap(b1, b2):
                collisions += 1
                faults.append(f"collision: {entity_text(e1)[:30]!r} x {entity_text(e2)[:30]!r}")
                say(f"  [{e1.dxf.layer:15s}] {entity_text(e1)[:34]!r}")
                say(f"     overlaps [{e2.dxf.layer:15s}] {entity_text(e2)[:34]!r}")
    if not collisions:
        say("  none")

    # ---- areas ------------------------------------------------------------
    say("\n=== areas ===")
    bdy = [e for e in msp.query("LWPOLYLINE[layer=='C-PLOT-BDY']")]
    bdy_area = None
    if bdy:
        pts = bdy[0].get_points("xy")
        bulges = [p[4] for p in bdy[0].get_points()]
        bdy_area = polygon_area(pts)
        arc = " (has arc segments; AutoCAD AREA will differ)" if any(bulges) else ""
        say(f"  boundary polyline : {bdy_area:10.2f} m2  ({len(pts)} verts){arc}")
    printed = None
    for e, _ in texts:
        t = entity_text(e)
        if "GROSS PLOT AREA" in t:
            for tok in t.replace(":", " ").split():
                try:
                    printed = float(tok)
                    break
                except ValueError:
                    continue
    discloses = any("MEASURED (BDY)" in entity_text(e) for e, _ in texts)
    if printed is not None:
        say(f"  printed on sheet  : {printed:10.2f} m2")
        if bdy_area:
            d = (bdy_area - printed) / printed * 100.0
            say(f"  delta             : {bdy_area - printed:+10.2f} m2 ({d:+.2f}%)")
            # A gap between MCGM's record and MCGM's own digitised polygon is real
            # data, not a bug - AMBIVALI 807 is 6.10% apart. What matters is that
            # the sheet admits it, so nobody computes FSI off an unreconciled
            # figure. Silence is the fault, not the discrepancy.
            if abs(d) > 2.0 and not discloses:
                faults.append(
                    f"boundary measures {d:+.2f}% vs the printed area, and the sheet "
                    "does not disclose the measured value")
            elif abs(d) > 2.0:
                say(f"  -> {d:+.2f}% gap, disclosed on the sheet via MEASURED (BDY)")
    else:
        faults.append("no plot area printed on the sheet")

    # ---- annotation scale -------------------------------------------------
    say("\n=== annotation scale vs plot size ===")
    if bdy:
        pts = bdy[0].get_points("xy")
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        pw, ph = max(xs) - min(xs), max(ys) - min(ys)
        say(f"  plot bounding box : {pw:.2f} x {ph:.2f} m")
        worst = None
        for _i, e, b in drawing:
            ratio = (b[2] - b[0]) / max(pw, 1e-6)
            if worst is None or ratio > worst[0]:
                worst = (ratio, e, b)
        if worst:
            ratio, e, b = worst
            say(f"  widest annotation : {b[2]-b[0]:.2f} m = {ratio:.2f}x plot width")
            say(f"                      {entity_text(e)[:60]!r}")
            # On a small plot any readable text is wide relative to the plot -- a
            # 7.6 m frontage cannot hold a road name at legible cap height. That is
            # inherent, and harmless while the label sits outside the boundary,
            # which the collision and border checks above already enforce. So this
            # is a proportion warning, and only egregious cases fail.
            if ratio > 3.0:
                faults.append(
                    f"annotation is {ratio:.2f}x the plot width - unreadable at plot scale")
            elif ratio > 1.5:
                say(f"  -> note: {ratio:.2f}x plot width. Acceptable (it sits outside the "
                    "boundary) but cramped on a small plot.")

    # ---- layers -----------------------------------------------------------
    say("\n=== layers ===")
    used = {e.dxf.layer for e in msp}
    declared = {lay.dxf.name for lay in doc.layers} - {"0", "Defpoints"}
    empty = sorted(declared - used)
    if empty:
        faults.append(f"declared but empty layers: {', '.join(empty)}")
        say(f"  EMPTY: {', '.join(empty)}")
    else:
        say(f"  all {len(declared)} declared layers carry entities")
    flat = sorted(lay.dxf.name for lay in doc.layers
                  if lay.dxf.name not in ("0", "Defpoints") and lay.dxf.lineweight < 0)
    if flat:
        faults.append(f"{len(flat)} layers have no lineweight and will plot flat")
        say(f"  NO LINEWEIGHT ({len(flat)}): {', '.join(flat)}")
    else:
        say("  every layer carries an explicit lineweight")

    # ---- frontage present when one is claimed ------------------------------
    # This audit reported 27/27 clean while AMBIVALI 807 had no road drawn at all.
    # Absence is not something the collision and containment checks can see, so it
    # has to be asserted directly: if PLOT DATA names an abutting road, the road
    # layer must carry geometry. The frontage governs the front setback, so a sheet
    # that names a road but does not draw it is worse than one that admits neither.
    say("\n=== abutting road ===")
    road_row = next((entity_text(e) for e, _ in texts if "ABUTTING ROAD" in entity_text(e)), "")
    claimed = road_row.split(":", 1)[-1].strip() if road_row else ""
    has_name = bool(claimed) and claimed.lower() not in ("n/a", "none", "none (none)", "")
    road_polys = [e for e in msp if e.dxf.layer == "C-ROAD-ALIGN"
                  and e.dxftype() == "LWPOLYLINE"]
    say(f"  PLOT DATA says   : {claimed[:60]!r}")
    say(f"  road polylines   : {len(road_polys)}")
    if has_name and not road_polys:
        faults.append(
            f"PLOT DATA names a frontage ({claimed[:40]!r}) but no road geometry is "
            "drawn, so the front setback cannot be identified")
    elif not has_name:
        say("  -> no frontage named by MCGM; nothing to draw")

    hatches = list(msp.query("HATCH"))
    for h in hatches:
        opaque = h.dxf.solid_fill and not h.dxf.hasattr("transparency")
        say(f"  hatch on {h.dxf.layer}: pattern={h.dxf.pattern_name} "
            f"solid={h.dxf.solid_fill} {'OPAQUE' if opaque else 'transparent'}")
        if opaque:
            faults.append("hatch is an opaque solid fill and will hide any underlay")

    if out is not None:
        print("\n".join(out))
    print(f"\n{'FAULTS: ' + str(len(faults)) if faults else 'CLEAN'}")
    for f in faults:
        print(f"  - {f}")
    return 1 if faults else 0


if __name__ == "__main__":
    sys.exit(main())
