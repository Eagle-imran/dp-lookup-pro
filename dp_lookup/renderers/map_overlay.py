"""
DP Zoning Map Overlay Renderer with North Arrow and Plot Callouts.
"""
import io
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageDraw


def render_dp_map(
    base_png: Optional[bytes],
    rings: list,
    bbox: Tuple[float, float, float, float],
    size: Tuple[int, int],
    labels: Dict[str, Any],
) -> Image.Image:
    """
    DP zoning map with the plot outlined, north arrow, and legend swatch.
    """
    x0, y0, x1, y1 = bbox
    width, height = size

    if base_png:
        base = Image.open(io.BytesIO(base_png)).convert("RGBA")
    else:
        base = Image.new("RGBA", (width, height), (240, 240, 240, 255))

    overlay = Image.new("RGBA", base.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    def to_px(x, y):
        return ((x - x0) / (x1 - x0) * width, (y1 - y) / (y1 - y0) * height)

    for ring in rings:
        draw.polygon([to_px(p[0], p[1]) for p in ring],
                     fill=(255, 23, 68, 45), outline=(255, 23, 68, 255), width=5)

    # North arrow
    nx, ny = width - 80, 80
    draw.ellipse([nx - 30, ny - 30, nx + 30, ny + 30],
                 fill=(255, 255, 255, 230), outline=(0, 0, 0, 255), width=2)
    draw.polygon([(nx, ny - 22), (nx - 10, ny + 12), (nx + 10, ny + 12)], fill=(220, 0, 0, 255))
    draw.text((nx - 5, ny - 48), "N", fill=(0, 0, 0, 255), font_size=24)

    lw, lh = 420, 160
    lx0, ly0 = width - lw - 30, height - lh - 30
    draw.rectangle([lx0, ly0, lx0 + lw, ly0 + lh],
                   fill=(255, 255, 255, 235), outline=(0, 0, 0, 255), width=2)
    draw.rectangle([lx0 + 20, ly0 + 20, lx0 + 50, ly0 + 42],
                   fill=(255, 23, 68, 100), outline=(255, 23, 68, 255), width=2)
    draw.text((lx0 + 60, ly0 + 20), f"Plot Boundary (CTS {labels['cts']})",
              fill=(0, 0, 0, 255), font_size=18)
    draw.text((lx0 + 20, ly0 + 55), f"Village: {labels['village']} | Ward: {labels['ward']}",
              fill=(0, 0, 0, 255), font_size=16)
    draw.text((lx0 + 20, ly0 + 85), f"Zone: {labels['zone']} | Area: {labels['area']} sq m",
              fill=(0, 0, 0, 255), font_size=16)
    draw.text((lx0 + 20, ly0 + 115), f"Status: {labels['status']}",
              fill=(0, 0, 0, 255), font_size=16)

    return Image.alpha_composite(base, overlay)
