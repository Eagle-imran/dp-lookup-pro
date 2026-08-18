"""Pure ArcGIS REST payload construction."""

from typing import Dict, Sequence

from dp_lookup.core.constants import PLANNING_LAYER_IDS


def identify_payload(
    x: float,
    y: float,
    layers: str,
    mcx: float,
    mcy: float,
    d: float,
    tolerance: int,
    return_geometry: bool,
) -> Dict[str, str]:
    return {
        "geometry": f"{x},{y}",
        "geometryType": "esriGeometryPoint",
        "sr": "102100",
        "layers": layers,
        "tolerance": str(tolerance),
        "mapExtent": f"{mcx - d},{mcy - d},{mcx + d},{mcy + d}",
        "imageDisplay": "1000,1000,96",
        "returnGeometry": "true" if return_geometry else "false",
        "f": "json",
    }


def spatial_query_payload(bbox_str: str, out_sr: str = "102100") -> Dict[str, str]:
    return {
        "geometry": bbox_str,
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "inSR": out_sr,
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": out_sr,
        "f": "json",
    }


def planning_layers(crz_layer_ids: Sequence[int]) -> str:
    ids = ",".join(str(layer_id) for layer_id in PLANNING_LAYER_IDS + list(crz_layer_ids))
    return f"visible:{ids}"


def map_export_params(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    width: int = 1000,
    height: int = 1000,
    dpi: int = 144,
) -> Dict[str, str]:
    return {
        "bbox": f"{x0},{y0},{x1},{y1}",
        "bboxSR": "102100",
        "imageSR": "102100",
        "size": f"{width},{height}",
        "format": "png",
        "transparent": "false",
        "dpi": str(dpi),
        "layers": "show:0,44,45,46,47,192,193,194,2224",
        "f": "image",
    }
