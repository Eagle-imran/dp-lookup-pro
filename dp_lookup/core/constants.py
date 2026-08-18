"""
MCGM Development Plan 2034 GIS Constants & Layer Definitions.
"""
import re
from typing import Tuple

SERVER_URL = "https://agsmaps.mcgm.gov.in/server/rest/services/Development_Plan_2034/MapServer"
APPLICATION_VERSION = "3.14.0"
RESULT_SCHEMA_VERSION = 1
CACHE_SCHEMA_VERSION = 1

# Web Mercator projection sphere radius
WEB_MERCATOR_R = 20037508.342789244

DEFAULT_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days
CACHE_FILENAME = ".cache_store.json"

# Layer IDs for MCGM Development Plan 2034 GIS Server
LAYER_ZONE = 0
LAYER_RESERVATION = 46
LAYER_DESIGNATION = 47
LAYER_MODIFICATION = 192
LAYER_METRO = 1550
CRZ_LAYER_IDS: Tuple[int, ...] = (14, 1264, 1548)

PLANNING_LAYER_IDS = [0, 46, 47, 192, 1550]  # zone, reservation, designation, DP mod, metro
ROAD_LAYERS = "visible:193,194,44,45,2224"
NEIGHBOUR_LAYERS = "visible:13"

# Minimum threshold to filter out digitisation noise / slivers on cadastral borders
SLIVER_AREA_THRESHOLD_SQM = 5.0
SLIVER_PERCENT_THRESHOLD = 0.001  # 0.1% of parcel area

# Probe offsets outward from each boundary edge, in Web Mercator units.
ROAD_EDGE_NUDGES = (6.0, 15.0, 25.0)
ROAD_EDGE_PROBE_LIMIT = 12

# MCGM records unnamed carriageway under several placeholder names
GENERIC_ROAD_NAMES = ("", "existing", "exisiting road", "null", "none", "road", "unknown")

# Input validation regexes
_VILLAGE_RE = re.compile(r"^[A-Za-z0-9 ()./-]{1,64}$")
_CTS_RE = re.compile(r"^[A-Za-z0-9 ()./-]{1,32}$")

# The 128 valid MCGM revenue village names, read from layer 13 on 2026-07-28.
MCGM_VILLAGES: Tuple[str, ...] = (
    "AAKSE", "AAREY", "AKURLI", "AMBIVALI", "ANDHERI", "ANIK", "ASALPE", "BANDIVALI",
    "BANDRA-A", "BANDRA-B", "BANDRA-C", "BANDRA-D", "BANDRA-E", "BANDRA-EAST",
    "BANDRA-F", "BANDRA-G", "BANDRA-H", "BANDRA-I", "BAPNALA", "BHANDUP-E", "BHANDUP-W",
    "BHULESHWAR", "BORIVALI", "BORLA", "BRAMHANWADA", "BYCULLA", "CHAKALA", "CHANDIVALI",
    "CHARKOP", "CHEMBUR", "CHINCHAVALI", "COLABA", "DADAR-NAIGAON", "DAHISAR", "DARAVALI",
    "DEONAR", "DHARAVI", "DINDOSHI", "EKSAR", "ERANGAL", "FORT", "GHATKOPAR",
    "GHATKOPAR KIROL", "GIRGAUM", "GORAI", "GOREGAON", "GUNDAVALI", "GUNDHGAON",
    "HARIYALI-E", "HARIYALI-W", "ISMALIA", "JUHU", "KANDIVALI", "KANHERI", "KANJUR-E",
    "KANJUR-W", "KIROL", "KLERABAD", "KOLEKALYAN", "KOLEKALYAN UNIVERSITY", "KONDIVATE",
    "KOPRI", "KURAR", "KURLA - 1", "KURLA - 2", "KURLA - 3", "KURLA - 4", "LOWER PAREL",
    "MADH", "MAGATHANE", "MAHIM", "MAHUL", "MAJAS", "MALABAR HILL", "MALAD", "MALAD-E",
    "MALAD-NORTH", "MALAD-SOUTH", "MALVANI", "MANDALE", "MANDPESHWAR-M", "MANDPESHWAR-N",
    "MANDPESHWAR-S", "MANDVI", "MANKHURD", "MANORI", "MARAVALI", "MAROL", "MAROL MAROSHI",
    "MARVE", "MATUNGA", "MAZAGAON", "MOGRA", "MOHILI", "MULGAON", "MULUND-E", "MULUND-W",
    "NAHUR", "OSHIWARA", "PAHADI EKSAR", "PAHADI GOREGAON-E", "PAHADI GOREGAON-W",
    "PAREL-SEWERI", "PARIGHIKARI", "PASPOLI", "POISAR", "POWAI", "PRAJAPUR",
    "PRINCESS DOCK", "SAAI", "SAHAR", "SAKI", "SALT PAN", "SHIMPAWALI", "SION", "TARDEO",
    "TIRANDAZ", "TULSI", "TUNGWE", "TURBHE", "VALNAI", "VERSOVA", "VIKHROLI", "VILE PARLE",
    "VYARAVLI", "WADHAVALI", "WADHWAN", "WORLI",
)
