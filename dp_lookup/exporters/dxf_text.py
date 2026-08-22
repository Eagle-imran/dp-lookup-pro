"""Text measurement, fitting and collision handling for DXF output."""

from __future__ import annotations

import math
from typing import Any, Optional, Sequence, Tuple

from dp_lookup.exporters.dxf_policy import DEFAULT_DXF_LAYOUT_POLICY, DxfLayoutPolicy

Box = Tuple[float, float, float, float]
Point = Tuple[float, float]


def fit_label_to_width(
    template: str,
    value: str,
    max_width: float,
    char_h: float,
    min_value_chars: Optional[int] = None,
    *,
    policy: DxfLayoutPolicy = DEFAULT_DXF_LAYOUT_POLICY,
) -> str:
    """Fit a text label inside a width budget."""
    per_char = max(char_h, 1e-6) * 0.72
    budget = int(max_width / per_char) - len(template.format(""))
    if budget >= len(value):
        return template.format(value)
    keep = max(min_value_chars if min_value_chars is not None else policy.label_min_value_chars, budget - 3)
    return template.format(value[:keep].rstrip(" ,.") + "...")


def text_extents(entity: Any) -> Optional[Box]:
    """Return the rendered bounding box of a TEXT entity."""
    try:
        from ezdxf.tools.text_size import text_size

        size = text_size(entity)
        width, height = size.width, size.cap_height
    except Exception:
        try:
            height = float(entity.dxf.height)
            width = len(entity.dxf.text) * height * 0.72
        except Exception:
            return None

    halign = int(getattr(entity.dxf, "halign", 0) or 0)
    valign = int(getattr(entity.dxf, "valign", 0) or 0)
    try:
        if (halign or valign) and entity.dxf.hasattr("align_point"):
            anchor = entity.dxf.align_point
        else:
            anchor = entity.dxf.insert
        x, y = float(anchor[0]), float(anchor[1])
    except Exception:
        return None

    offset_x = -width * {1: 0.5, 2: 1.0, 4: 0.5}.get(halign, 0.0)
    offset_y = -height * (0.5 if halign == 4 else {2: 0.5, 3: 1.0}.get(valign, 0.0))
    rotation = math.radians(float(getattr(entity.dxf, "rotation", 0.0) or 0.0))
    if not rotation:
        return (x + offset_x, y + offset_y, x + offset_x + width, y + offset_y + height)
    cos_rotation, sin_rotation = math.cos(rotation), math.sin(rotation)
    points = [
        (x + dx * cos_rotation - dy * sin_rotation, y + dx * sin_rotation + dy * cos_rotation)
        for dx, dy in (
            (offset_x, offset_y),
            (offset_x + width, offset_y),
            (offset_x + width, offset_y + height),
            (offset_x, offset_y + height),
        )
    ]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def boxes_overlap(a: Optional[Box], b: Optional[Box], slack: float = 0.0) -> bool:
    """Return whether two axis-aligned bounding boxes intersect."""
    if a is None or b is None:
        return False
    return not (a[2] + slack < b[0] or b[2] + slack < a[0] or a[3] + slack < b[1] or b[3] + slack < a[1])


def nudge_text_clear(
    entity: Any,
    obstacles: Sequence[Box],
    step: float,
    direction: Point = (0.0, 1.0),
    limit: int = 10,
) -> bool:
    """Shift a label along a direction until it clears existing obstacles."""
    if step <= 0:
        return True
    dx, dy = direction
    for _ in range(limit + 1):
        box = text_extents(entity)
        if box is None:
            return True
        if not any(boxes_overlap(box, other) for other in obstacles):
            return True
        insertion = entity.dxf.insert
        entity.set_placement((float(insertion[0]) + dx * step, float(insertion[1]) + dy * step))
    return False
