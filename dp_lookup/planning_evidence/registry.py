"""Audited, dependency-free registry of MCGM Development Plan layers.

The registry is data only.  It performs no network or filesystem I/O and has no
dependency on the application's ArcGIS clients.  Keep source observations and
legal interpretation separate: these specs describe what to query and how to
classify the returned evidence; they do not decide whether a parcel is legally
developable.
"""

from typing import Dict, Iterable, Optional, Sequence, Tuple

from dp_lookup.planning_evidence.models import (
    EvidenceClass,
    EvidenceContext,
    EvidenceMode,
    LayerSpec,
    QueryPolicy,
)

SERVER_URL = "https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer"

# Source aliases observed in the map service.  Query only the canonical source
# once; retaining this mapping makes the audit trail explicit when a caller
# starts with a duplicate/legacy layer ID.
CANONICAL_LAYER_IDS: Dict[int, int] = {
    57: 61,
    2251: 2250,
    2252: 2250,
}


def _spec(
    layer_id: int,
    name: str,
    evidence_class: EvidenceClass,
    role: str,
    *,
    out_fields: Tuple[str, ...] = ("OBJECTID",),
    query_policy: QueryPolicy = QueryPolicy.ALWAYS,
    geometry_type: str = "esriGeometryPolygon",
    object_id_field: str = "OBJECTID",
    canonical_id: Optional[int] = None,
    audit_note: str = "Audited against the MCGM Development_Plan_2034 MapServer; spatial overlap is screening evidence only.",
) -> LayerSpec:
    return LayerSpec(
        layer_id=layer_id,
        name=name,
        evidence_class=evidence_class,
        query_policy=query_policy,
        out_fields=out_fields,
        role=role,
        geometry_type=geometry_type,
        object_id_field=object_id_field,
        canonical_id=canonical_id,
        audit_note=audit_note,
    )


# The first group documents the current lookup contract. The optional evidence
# service selects only the curated STANDARD/FULL IDs below; it never re-queries
# Layer 13 or replaces the established planning pipeline.
LAYER_SPECS: Tuple[LayerSpec, ...] = (
    _spec(13, "Global_Property_merge_v7", EvidenceClass.CONTEXTUAL, "CTS cadastral parcel", out_fields=("OBJECTID", "VILLAGE", "CTS_CS_NO", "WARD")),
    _spec(0, "REVISED PLU ZONES", EvidenceClass.REGULATORY, "DP zoning", out_fields=("OBJECTID", "ZONE_CODE2")),
    _spec(46, "PLU_RESERVATION", EvidenceClass.REGULATORY, "DP reservation", out_fields=("OBJECTID", "NEW_RES_CODE_31", "NEW_RES_MAINTYPE_31", "DISCRIPTION", "U_R_ID", "FINAL_RES_CODE", "FINAL_RES_MAINTYPE")),
    _spec(47, "PLU_DESIGNATION", EvidenceClass.REGULATORY, "DP designation", out_fields=("OBJECTID", "NEW_DES_CODE_31", "NEW_DES_MAINTYPE_31", "DISCRIPTION", "U_D_ID", "FINAL_DES_CODE", "FINAL_DES_MAINTYPE")),
    _spec(192, "CorrectionsNotification", EvidenceClass.REGULATORY, "DP modification/correction", out_fields=("OBJECTID", "PUBLISHED_PROVISION", "CORRECTED_PROVISION", "LABEL", "APPROVAL_NO", "APPROVED_BY", "APPROVAL_DOCUMENTS", "REMARKS", "MODIFNUM")),
    _spec(
        1550,
        "Metro_buffer",
        EvidenceClass.REGULATORY,
        "Metro rail influence buffer",
        out_fields=("OBJECTID_1",),
        object_id_field="OBJECTID_1",
    ),
    _spec(14, "CRZ", EvidenceClass.REGULATORY, "legacy CRZ zone polygon", out_fields=("OBJECTID", "CATEGORY")),
    _spec(1264, "CRZ II", EvidenceClass.REGULATORY, "legacy CRZ II polygon", out_fields=("OBJECTID", "CLASS")),
    _spec(1548, "CRZ category", EvidenceClass.REGULATORY, "legacy CRZ zone polygon", out_fields=("OBJECTID", "CATEGORY")),
    _spec(
        193,
        "Traffic RoadLines",
        EvidenceClass.CONTEXTUAL,
        "traffic road alignment",
        out_fields=("OBJECTID_1",),
        geometry_type="esriGeometryPolyline",
        object_id_field="OBJECTID_1",
    ),
    _spec(194, "Survey RoadLines", EvidenceClass.CONTEXTUAL, "survey road alignment", geometry_type="esriGeometryPolyline"),
    _spec(44, "EXISITING_ROAD", EvidenceClass.REGULATORY, "existing road reservation"),
    _spec(45, "PROPOSED_ROAD", EvidenceClass.REGULATORY, "proposed road reservation"),
    _spec(2224, "Roads", EvidenceClass.REGULATORY, "CRZ road polygon", query_policy=QueryPolicy.COASTAL),

    _spec(2000, "MRTP_37_Modification", EvidenceClass.STATUTORY, "MRTP Section 37 decision evidence", out_fields=("OBJECTID", "PLU_TYPE", "PUBLISHED_PROVISION", "CORRECTED_PROVISION", "LABEL", "WARD", "NOTIFICATION_NO", "APPROVED_BY", "APPROVAL_DOCUMENTS", "REMARKS", "DP_CORRECTION_NO")),
    _spec(83, "Sanctioned_EP", EvidenceClass.STATUTORY, "EP decision evidence", out_fields=("OBJECTID", "EP_NO", "EP_DECISIO", "SANCTION_DECISIO", "SANCTION_DECISION2", "WARD", "NOTIFICATION_NO", "GAZETTE_DATE")),
    _spec(61, "Modification_With_EP", EvidenceClass.CONTEXTUAL, "EP amendment history", out_fields=("OBJECTID_12", "WARD_1", "MOD_NO", "LAYAR", "OLD_CODE", "NEW_CODE", "MODIFICATI", "MOD_REMARK", "EP_NO", "EP_CODE", "SM_NO", "SM_CODE", "EP_DECISIO", "SM_DECISIO", "MODIFNUM", "APPROVAL_NO", "APPROVED_BY", "APRDOCS", "LAST_EDITED_DATE"), object_id_field="OBJECTID_12"),
    _spec(60, "Modification_With_SM", EvidenceClass.CONTEXTUAL, "SM amendment history", out_fields=("OBJECTID_12", "WARD_1", "MOD_NO", "LAYAR", "OLD_CODE", "NEW_CODE", "MODIFICATI", "MOD_REMARK", "EP_NO", "EP_CODE", "SM_NO", "SM_CODE", "EP_DECISIO", "SM_DECISIO", "MODIFNUM", "APPROVAL_NO", "APPROVED_BY", "APRDOCS", "LAST_EDITED_DATE"), object_id_field="OBJECTID_12"),
    _spec(57, "Modification_With_EP_SM", EvidenceClass.CONTEXTUAL, "duplicate EP/SM history", out_fields=("OBJECTID_12",), object_id_field="OBJECTID_12", canonical_id=61),
    _spec(85, "Relocation_Reconstitution", EvidenceClass.REGULATORY, "reservation relocation/reconstitution", out_fields=("OBJECTID", "PLU_TYPE", "WARD", "PLU_MAINTYPE", "RES_DES_DP2034_CODE", "RES_DES_NAME", "RES_DES_NUMBER", "APPROVAL_NUMBER", "APPROVED_BY", "INTENT_LETTER_WITH_DATE", "REMARK", "APRDOCS", "MODIFNUM", "ORIGINAL_RESERVATION_CTS", "RELOCATED_RESERVATION_CTS")),
    _spec(92, "Corrections As per DCPR2034", EvidenceClass.REGULATORY, "approved municipal/DCPR correction evidence", out_fields=("OBJECTID", "PLU_TYPE", "PUBLISHED_PROVISION", "CORRECTED_PROVISION", "LABEL", "WARD", "APPROVAL_NO", "APPROVED_BY", "APPROVAL_DOCUMENTS", "REMARKS", "MODIFNUM")),
    _spec(81, "Road_Realignment", EvidenceClass.REGULATORY, "approved road realignment evidence", out_fields=("OBJECTID", "ROAD_TYPE", "ROAD_WIDTH", "NAME_ARCHITECT_OWNER", "APPROVAL_NO", "APPROVED_BY", "WARD", "WARD_ZONE", "APRDOCS", "MODIFNUM", "LAST_EDITED_DATE")),

    _spec(2250, "CZMP 2019", EvidenceClass.REGULATORY, "consolidated coastal-zone screening", out_fields=("OBJECTID", "CATEGORY", "SUB_CATGORY", "LAST_EDITED_DATE")),
    _spec(2251, "CZMP 2019 duplicate 2251", EvidenceClass.REGULATORY, "duplicate coastal source", out_fields=("OBJECTID",), canonical_id=2250),
    _spec(2252, "CZMP 2019 duplicate 2252", EvidenceClass.REGULATORY, "duplicate coastal source", out_fields=("OBJECTID",), canonical_id=2250),
    _spec(77, "Heritage", EvidenceClass.REGULATORY, "heritage structure screening", out_fields=("OBJECTID_1", "HERITAGE_NAME", "HERITAGE_P", "GRADE", "VILLAGE", "WARD", "OWNERSHIP", "USES", "MHCC_NOC", "DATE_", "NOC_FOR", "REMARKS", "EDIT_REMARK", "HER_NUMBER_2"), object_id_field="OBJECTID_1"),
    _spec(78, "Precinct", EvidenceClass.REGULATORY, "heritage precinct screening", out_fields=("OBJECTID_1", "NAME", "CODE", "REMARKS", "WARD", "SUB_PRECINCT_NAME", "PRECINCT_NUMBER", "PRECINCT_NAME", "LAST_EDI_1"), object_id_field="OBJECTID_1"),
    _spec(79, "Heritage_Buffer", EvidenceClass.REGULATORY, "heritage/ASI buffer screening", out_fields=("OBJECTID_12", "SCANTION_N", "SCANTION_D", "NAME", "GRADE", "HER_NUMBER", "REMARK", "BUFFER"), object_id_field="OBJECTID_12"),
    _spec(29, "ASI_MONUMENTS_100m_BUFFER", EvidenceClass.REGULATORY, "ASI 100 m prohibited-area screening", out_fields=("OBJECTID", "NAME", "WARD", "BUFF_DIST", "ORIG_FID")),
    _spec(30, "ASI_MONUMENTS_200m_Buffer", EvidenceClass.REGULATORY, "ASI 300 m outer extent for derived 200 m regulated band", out_fields=("OBJECTID", "NAME", "WARD", "BUFF_DIST", "ORIG_FID")),
    _spec(20, "RAILWAY_30M_BUFFER", EvidenceClass.REGULATORY, "railway buffer"),
    _spec(19, "HIGHWAY_45_M_Buffer", EvidenceClass.REGULATORY, "highway buffer screening", out_fields=("OBJECTID", "TYPE")),
    _spec(197, "MAHSR_Buffer", EvidenceClass.REGULATORY, "high-speed rail buffer", out_fields=("OBJECTID", "LABEL")),
    _spec(16, "HVL_Buffer", EvidenceClass.REGULATORY, "high-voltage buffer"),
    _spec(1149, "SGNP_Eco_Sensitive", EvidenceClass.REGULATORY, "SGNP eco-sensitive-zone screening"),
    _spec(
        48,
        "WATER_BODIES",
        EvidenceClass.REGULATORY,
        "water body",
        out_fields=("OBJECTID_1", "WARD"),
        object_id_field="OBJECTID_1",
    ),
    _spec(49, "WATER_BUFFERS", EvidenceClass.REGULATORY, "water body buffer"),
    _spec(72, "MBPT_BOUNDARY", EvidenceClass.CONTEXTUAL, "port/MBPT boundary"),
    _spec(1210, "Koliwada", EvidenceClass.CONTEXTUAL, "mapped Koliwada boundary", out_fields=("OBJECTID", "NAME", "TYPE", "VILLAGE", "WARD")),
    _spec(1211, "Gaothan", EvidenceClass.CONTEXTUAL, "mapped Gaothan boundary", out_fields=("OBJECTID", "GONTHAN_NAME", "WARD_NAME", "VILLAGE_NAME", "TIKKA_SHEET_NO", "SHEET_NO", "LAST_EDITED_DATE")),
    _spec(2400, "Amenities", EvidenceClass.CONTEXTUAL, "amenity possession/acquisition inventory", out_fields=("OBJECTID", "UID_", "WARD", "FILE_NO", "CTS_NO", "VILLAGE", "RESERVATION", "RESERVATION_DISCRIPTION", "AREA_IN_SQ_MTR", "STATUS_OF_SITE_V_FE_PE_D_MG_IH", "DATE_OF_POSSESSION", "USER_DEPARTMENT", "PRESENT_SITE_STATUS", "MODE_OF_ACQUISITION_TDR_FSI_AC", "REMARK", "RES_MAINTYPE", "LAST_EDITED_DATE")),

    _spec(112, "tps_property", EvidenceClass.CONTEXTUAL, "TPS applicability/property context", out_fields=("OBJECTID", "WARD", "VILLAGE_NAME", "TPS_NAME", "PROPERTY_TYPE", "CTS_CS_NO", "FP_NO", "PLOT_NO", "TENURE", "OWNERSHIP", "COMPETENT_AUTHORITY", "REFFERENCE", "REMARKS", "APR_NO", "APR_DATE")),
    _spec(105, "TPS_Zones", EvidenceClass.CONTEXTUAL, "legacy TPS zoning", query_policy=QueryPolicy.TPS, out_fields=("OBJECTID", "NAME", "TYPE")),
    _spec(107, "TPS_Reservations", EvidenceClass.CONTEXTUAL, "legacy TPS reservation", query_policy=QueryPolicy.TPS, out_fields=("OBJECTID", "RESERV_AREA", "RES_CODE", "RESERVATION", "RES_NUMBER", "NAME", "VILLAGE", "WARD", "UIDRES")),
    _spec(110, "TPS_Nallas", EvidenceClass.CONTEXTUAL, "legacy TPS nalla", query_policy=QueryPolicy.TPS, out_fields=("OBJECTID", "NAME", "REMARKS")),
    _spec(111, "TPS_Roads", EvidenceClass.CONTEXTUAL, "legacy TPS road polygon", query_policy=QueryPolicy.TPS, out_fields=("OBJECTID", "NAME", "TPS_NAME", "WIDTH", "TYPE", "SUB_TYPE", "REMARKS")),

    _spec(1524, "ELU_block_bnd", EvidenceClass.CONTEXTUAL, "SPA applicability boundary", out_fields=("OBJECTID_1", "NAME", "AUTHORITY", "TYPE", "WARD", "NO_"), object_id_field="OBJECTID_1"),
    _spec(1540, "SPA_Reservations", EvidenceClass.REGULATORY, "SPA reservation", query_policy=QueryPolicy.SPA, out_fields=("OBJECTID", "WARD", "RES_REMARK", "NEW_RES_CO", "NEW_RES_MA", "CODE_LABEL", "RES_ID", "RES_AREA", "LAST_EDITED_DATE")),
    _spec(1541, "SPA_Designations", EvidenceClass.REGULATORY, "SPA designation", query_policy=QueryPolicy.SPA, out_fields=("OBJECTID", "WARD", "DES_REMARK", "NEW_DES_CO", "NEW_DES_MA", "CODE_LABEL", "DES_ID", "DES_AREA", "LAST_EDITED_DATE")),
    _spec(1544, "SPA_Landuse_zones", EvidenceClass.REGULATORY, "SPA land-use zone", query_policy=QueryPolicy.SPA, out_fields=("OBJECTID_1", "ZONE_CODE2", "SPA_BLOCK", "LAST_EDITED_DATE"), object_id_field="OBJECTID_1"),

    _spec(1502, "GORAI MANORI Notified Area", EvidenceClass.CONTEXTUAL, "Gorai-Manori applicability boundary"),
    _spec(1104, "Landuse_zones", EvidenceClass.REGULATORY, "Gorai-Manori land-use zone", query_policy=QueryPolicy.GORAI, out_fields=("OBJECTID", "ZONE_TYPE", "ZONE_NAME", "ZONE_CODE", "MAIN_ZONE_TYPE", "MOD_NO", "EP_NO", "SM_NO", "FINAL_REMARKS", "NEW_MAINTYPE", "NEW_ZONECODE", "NEW_ZONENAME")),
    _spec(1121, "Designation", EvidenceClass.REGULATORY, "Gorai-Manori designation", query_policy=QueryPolicy.GORAI, out_fields=("OBJECTID", "WARD", "NEW_DES_CODE", "NEW_DES_MAINTYPE", "CODE_LABEL", "NAME", "EP_NO", "SM_NO", "FINAL_REMARK")),
    _spec(1122, "Reservations", EvidenceClass.REGULATORY, "Gorai-Manori reservation", query_policy=QueryPolicy.GORAI, out_fields=("OBJECTID", "WARD", "NEW_RES_CODE", "NEW_RES_MAINTYPE", "CODE_LABEL", "NAME", "EP_NO", "SM_NO", "FINAL_REMARK")),
    _spec(1126, "ExistingRoads", EvidenceClass.CONTEXTUAL, "Gorai-Manori existing road", query_policy=QueryPolicy.GORAI, out_fields=("OBJECTID", "REFERENCE", "WARD", "TYPE", "LOCATION", "DDP34_SHEET_NO_", "REMARK")),
    _spec(1127, "ProposedRoads", EvidenceClass.REGULATORY, "Gorai-Manori proposed road", query_policy=QueryPolicy.GORAI, out_fields=("OBJECTID", "WIDTH", "WARD", "TYPE", "ROADNAME", "SHEET_NO", "ROAD_TYPE2", "MOD_NO", "EP_NO", "FINAL_REMARK")),
)


CURRENT_CORE_LAYER_IDS: Tuple[int, ...] = (
    13, 0, 46, 47, 192, 1550, 14, 1264, 1548, 193, 194, 44, 45, 2224
)
STANDARD_LAYER_IDS: Tuple[int, ...] = (83, 2000, 92, 60, 61, 85, 81, 2250)
FULL_ALWAYS_LAYER_IDS: Tuple[int, ...] = (
    77, 78, 79, 29, 30, 20, 19, 197, 16, 1149, 48, 49, 72, 1210, 1211, 2400, 112, 1524, 1502
)


LAYER_REGISTRY: Dict[int, LayerSpec] = {spec.layer_id: spec for spec in LAYER_SPECS}


def canonical_layer_id(layer_id: int) -> int:
    """Resolve a source-layer alias to its canonical query layer."""

    current = int(layer_id)
    seen = set()
    while current in CANONICAL_LAYER_IDS:
        if current in seen:
            raise ValueError("canonical layer mapping contains a cycle")
        seen.add(current)
        current = CANONICAL_LAYER_IDS[current]
    return current


def get_layer_spec(layer_id: int, *, canonical: bool = False) -> Optional[LayerSpec]:
    """Return a registered spec, optionally resolving aliases first."""

    source_id = canonical_layer_id(layer_id) if canonical else int(layer_id)
    return LAYER_REGISTRY.get(source_id)


def get_canonical_spec(layer_id: int) -> Optional[LayerSpec]:
    """Return the canonical spec for a source ID or ``None`` if unregistered."""

    return get_layer_spec(layer_id, canonical=True)


def deduplicate_layer_specs(specs: Iterable[LayerSpec]) -> Tuple[LayerSpec, ...]:
    """Canonicalise and de-duplicate specs while preserving input order."""

    result = []
    seen = set()
    for spec in specs:
        canonical = get_canonical_spec(spec.layer_id) or spec
        if canonical.layer_id in seen:
            continue
        seen.add(canonical.layer_id)
        result.append(canonical)
    return tuple(result)


def applicable_layer_specs(
    specs: Iterable[LayerSpec] = LAYER_SPECS,
    *,
    context: Optional[EvidenceContext] = None,
    coastal: bool = False,
    tps: bool = False,
    spa: bool = False,
    gorai: bool = False,
) -> Tuple[LayerSpec, ...]:
    """Return canonical, de-duplicated specs applicable to parcel context."""

    active_context = context or EvidenceContext(coastal=coastal, tps=tps, spa=spa, gorai=gorai)
    return tuple(spec for spec in deduplicate_layer_specs(specs) if spec.is_applicable(active_context))


# Descriptive aliases make the small pure API easy to discover without adding
# another abstraction layer.
get_applicable_specs = applicable_layer_specs
deduplicated_specs = deduplicate_layer_specs


def specs_for_mode(
    mode: EvidenceMode,
    *,
    context: Optional[EvidenceContext] = None,
) -> Tuple[LayerSpec, ...]:
    """Return the curated, canonical query set for a runtime evidence mode."""

    selected_mode = EvidenceMode.parse(mode)
    if selected_mode is EvidenceMode.BASIC:
        return ()
    ids: Sequence[int] = STANDARD_LAYER_IDS
    if selected_mode is EvidenceMode.FULL:
        ids = (*STANDARD_LAYER_IDS, *FULL_ALWAYS_LAYER_IDS)
    specs = tuple(LAYER_REGISTRY[layer_id] for layer_id in ids)
    if selected_mode is not EvidenceMode.FULL:
        return deduplicate_layer_specs(specs)
    active_context = context or EvidenceContext()
    conditional = (
        spec
        for spec in LAYER_SPECS
        if spec.query_policy is not QueryPolicy.ALWAYS
        and spec.layer_id not in CURRENT_CORE_LAYER_IDS
        and spec.is_applicable(active_context)
    )
    return deduplicate_layer_specs((*specs, *tuple(conditional)))
