"""Place readable CTS labels on the report maps."""

from collections.abc import Sequence

from PIL import ImageDraw
from shapely.geometry import box

from dp_lookup.core.topology import arcgis_rings_to_geometry

PixelBox = tuple[float, float, float, float]


def visible_parcel_points(
    rings: Sequence[Sequence[Sequence[float]]], bounds: tuple[float, float, float, float]
) -> list[tuple[float, float]]:
    visible = arcgis_rings_to_geometry(rings).intersection(box(*bounds))
    parts = sorted(getattr(visible, "geoms", [visible]), key=lambda part: part.area, reverse=True)
    points = [part.representative_point() for part in parts if part.area > 0]
    return [(float(point.x), float(point.y)) for point in points]


def draw_cts_label(
    draw: ImageDraw.ImageDraw,
    point: tuple[float, float],
    text: str,
    size: tuple[int, int],
    occupied: list[PixelBox],
    *,
    font_size: int,
    color: str,
) -> None:
    """Keep labels inside the image, using a leader when they need to move."""
    left, top, right, bottom = draw.textbbox((0, 0), text, anchor="mm", font_size=font_size)
    pad_x, pad_y = 7, 4
    label_width = right - left + 2 * pad_x
    label_height = bottom - top + 2 * pad_y
    x, y = point
    width, height = size
    for dx, dy in (
        (0, 0), (0, -1), (0, 1), (1, 0), (-1, 0),
        (1, -1), (-1, -1), (1, 1), (-1, 1), (0, -2), (0, 2),
    ):
        cx = min(max(x + dx * label_width, 4 - left + pad_x), width - 4 - right - pad_x)
        cy = min(max(y + dy * (label_height + 6), 4 - top + pad_y), height - 4 - bottom - pad_y)
        rect = (cx + left - pad_x, cy + top - pad_y, cx + right + pad_x, cy + bottom + pad_y)
        x0, y0, x1, y1 = rect
        if x0 < 0 or y0 < 0 or any(
            x0 < other_right + 3 and x1 > other_left - 3 and y0 < other_bottom + 3 and y1 > other_top - 3
            for other_left, other_top, other_right, other_bottom in occupied
        ):
            continue
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            draw.line([point, (cx, cy)], fill="#171c24", width=5)
            draw.line([point, (cx, cy)], fill=color, width=2)
        draw.rounded_rectangle(rect, radius=4, fill="#171c24", outline=color, width=2)
        draw.text((cx, cy), text, anchor="mm", font_size=font_size, fill=color)
        occupied.append(rect)
        return
