"""
Esri World Imagery Satellite Tile Grid Stitcher and Boundary Highlighter.
"""
import io
from typing import Any, Dict, List, Tuple

from PIL import Image, ImageDraw


def stitch_satellite(
    tiles: List[Any],
    coords: List[Tuple[int, int]],
    grid_dim: int,
    wgs_rings: List[List[List[float]]],
    bounds: Tuple[float, float, float, float],
    labels: Dict[str, Any],
) -> Image.Image:
    """
    Esri tiles stitched into one canvas with the plot outlined.
    `bounds` is (top_lat, left_lon, bot_lat, right_lon) for the whole grid.
    """
    top_lat, left_lon, bot_lat, right_lon = bounds
    canvas_w = canvas_h = grid_dim * 256
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (40, 40, 40, 255))

    for (gx, gy), blob in zip(coords, tiles):
        if not blob or isinstance(blob, Exception):
            continue
        try:
            canvas.paste(Image.open(io.BytesIO(blob)).convert("RGBA"), (gx * 256, gy * 256))
        except Exception:
            continue

    overlay = Image.new("RGBA", (canvas_w, canvas_h), (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    def to_px(lon, lat):
        return ((lon - left_lon) / (right_lon - left_lon) * canvas_w,
                (top_lat - lat) / (top_lat - bot_lat) * canvas_h)

    for ring in wgs_rings:
        draw.polygon([to_px(p[0], p[1]) for p in ring],
                     fill=(255, 235, 59, 50), outline=(255, 235, 59, 255), width=5)

    slw, slh = 320, 110
    sx, sy = canvas_w - slw - 15, canvas_h - slh - 15
    draw.rectangle([sx, sy, sx + slw, sy + slh],
                   fill=(0, 0, 0, 210), outline=(255, 255, 255, 255), width=2)
    draw.rectangle([sx + 12, sy + 12, sx + 35, sy + 30],
                   fill=(255, 235, 59, 100), outline=(255, 235, 59, 255), width=2)
    draw.text((sx + 42, sy + 12), f"Satellite Boundary (CTS {labels['cts']})",
              fill=(255, 255, 255, 255), font_size=13)
    draw.text((sx + 12, sy + 38), f"Village: {labels['village']} | Ward: {labels['ward']}",
              fill=(255, 255, 255, 255), font_size=12)
    draw.text((sx + 12, sy + 60), f"Lat: {labels['lat']:.6f} | Lon: {labels['lon']:.6f}",
              fill=(255, 255, 255, 255), font_size=12)
    draw.text((sx + 12, sy + 82), f"Adjoining Parcels Identified: {labels['neighbours']}",
              fill=(255, 255, 255, 255), font_size=12)

    return Image.alpha_composite(canvas, overlay)
