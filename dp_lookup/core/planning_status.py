"""
Planning Status Classification & Municipal Attribute Derivation.
"""
from typing import Any, Dict, List, Optional

from dp_lookup.core.constants import GENERIC_ROAD_NAMES


def filesystem_identity_token(value: Any, *, lower: bool = False) -> str:
    """Encode an exact cadastral identity into a safe, collision-free token.

    Slash and hyphen are both meaningful in CTS numbers.  Replacing both with
    ``-`` made ``16/738`` overwrite ``16-738``; the ``~xx`` escape is readable,
    reversible, and cannot collide because ``~`` is not accepted user input.
    """
    text = str(value).strip()
    if lower:
        text = text.lower()
    return text.replace("~", "~7e").replace("/", "~2f").replace("\\", "~5c").replace(" ", "_")


def bundle_folder_name(village: Any, cts_number: Any) -> str:
    """Filesystem-safe bundle folder preserving exact cadastral identity."""
    cts_clean = filesystem_identity_token(cts_number)
    village_clean = filesystem_identity_token(village, lower=True)
    return f"{village_clean}_cts_{cts_clean}"


def select_road(road_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Pick the abutting road to report, best evidence first:
      1. a real name AND a recorded width
      2. a real name OR a recorded width
      3. whatever was found, so the field is never empty when something matched
    """
    def real_name(road: Dict[str, Any]) -> bool:
        return str(road.get("name") or "").strip().casefold() not in GENERIC_ROAD_NAMES

    def real_width(road: Dict[str, Any]) -> bool:
        return road.get("width") != "N/A"

    values = list(road_map.values())
    named_with_width = [r for r in values if real_width(r) and real_name(r)]
    named_or_width = [r for r in values if real_name(r) or real_width(r)]
    roads = named_with_width or named_or_width or values
    if not roads:
        return {"name": "None", "width": "None"}
    selected = roads[0]
    name = selected.get("name")
    if not real_name(selected):
        name = "Unnamed / existing road"
    return {"name": name, "width": selected.get("width") or "N/A"}


def crz_flag_from(crz_item: Optional[Dict[str, Any]]) -> str:
    """Report the CRZ sub-tier rather than a bare yes."""
    if not crz_item:
        return "NO (Outside CRZ Buffer)"
    attrs = crz_item.get("attributes", {}) or {}
    tier = None
    for key in ("category", "Category", "CATEGORY", "CLASS", "Class"):
        val = attrs.get(key)
        if val and str(val).strip().lower() not in ("", "null", "none"):
            tier = str(val).strip()
            break
    if not tier:
        return f"YES ({crz_item.get('layerName')})"
    label = tier if tier.upper().startswith("CRZ") else f"CRZ {tier}"
    return f"YES ({label})"


def derive_status(
    mod_item: Any = None,
    des_item: Any = None,
    rv_item: Any = None,
    des_desc: str = "None",
    des_code: str = "None",
    res_code: str = "None",
    res_type: str = "None",
    mod_approval: str = "None",
    *,
    reservations: Optional[List[Dict[str, Any]]] = None,
    designations: Optional[List[Dict[str, Any]]] = None,
    modifications: Optional[List[Dict[str, Any]]] = None,
    encumbered_percent: Optional[float] = None,
    encumbered_area_sqm: Optional[float] = None,
    total_area_sqm: Optional[float] = None,
    net_unencumbered_sqm: Optional[float] = None,
) -> Dict[str, str]:
    """
    Planning status badge and one-line summary, in precedence order:
      1. DP Modification Order (Sanctions / EPs) -> 🟡 MODIFIED
      2. Partial Reservation / Designation -> 🟡 PARTIALLY RESERVED / DESIGNATED
      3. Full Reservation / Designation (> 90%) -> 🔴 RESERVED
      4. Clear Parcel (0% encumbered) -> 🟢 CLEAR
    """
    if mod_item or (modifications and len(modifications) > 0):
        appr = mod_approval if mod_approval != "None" else (
            modifications[0].get("approval_no", "DP Mod") if modifications else "Order"
        )
        return {"badge": "\U0001F7E1 MODIFIED (DP Notification Order)",
                "summary": f"Modified via {appr}"}

    # Rich spatial encumbrance check if available
    if encumbered_percent is not None and (reservations is not None or designations is not None):
        res_list = reservations or []
        des_list = designations or []
        if encumbered_percent <= 0.0 or (not res_list and not des_list):
            return {"badge": "\U0001F7E2 CLEAR (No Reservation)",
                    "summary": "Unreserved Land Parcel"}

        if encumbered_percent < 90.0:
            partial_codes = [r["code"] for r in res_list] + [d["code"] for d in des_list]
            code_str = ", ".join(partial_codes[:3])
            enc_txt = f"{encumbered_area_sqm:,.1f} m²" if encumbered_area_sqm else f"{encumbered_percent:.1f}%"
            net_txt = f"{net_unencumbered_sqm:,.1f} m²" if net_unencumbered_sqm is not None else "N/A"
            if res_list and not des_list:
                badge_type = "PARTIALLY RESERVED"
            elif des_list and not res_list:
                badge_type = "PARTIALLY DESIGNATED"
            else:
                badge_type = "PARTIALLY RESERVED / DESIGNATED"

            return {
                "badge": f"\U0001F7E1 {badge_type} ({encumbered_percent:.1f}% - {code_str})",
                "summary": f"Partially encumbered ({enc_txt}). Net developable: {net_txt}",
            }

        # Heavily / Fully encumbered (>= 90%)
        if des_list and not res_list:
            d0 = des_list[0]
            return {
                "badge": f"\U0001F534 RESERVED / DESIGNATED ({d0.get('description', 'Designation')})",
                "summary": f"Designated as {d0.get('description', 'Designation')} ({d0.get('code', 'Des')})",
            }
        if res_list:
            reservation_types = ", ".join(r.get("type", "Reservation") for r in res_list[:2])
            reservation_codes = ", ".join(r.get("code", "Res") for r in res_list[:2])
            return {
                "badge": f"\U0001F534 RESERVED ({reservation_types})",
                "summary": f"Reserved under {reservation_codes}",
            }

    if des_item and des_desc != "None":
        return {"badge": f"\U0001F534 RESERVED / DESIGNATED ({des_desc})",
                "summary": f"Designated as {des_desc} ({des_code})"}
    if rv_item and res_code != "None":
        return {"badge": f"\U0001F534 RESERVED ({res_type})",
                "summary": f"Reserved under {res_code}"}
    return {"badge": "\U0001F7E2 CLEAR (No Reservation)",
            "summary": "Unreserved Land Parcel"}
