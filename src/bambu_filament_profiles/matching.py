"""Normalisation of brands, materials and product names.

The sources spell the same filaments differently ("eSUN 3D", "esun_3d", "eSUN";
"PLA+" and "PLA Plus"). Matching therefore uses a key made of the normalised
brand, the material family and the name tokens.
"""

from __future__ import annotations

import re

BRAND_ALIASES = {
    "bambu": "bambulab",
    "prusapolymers": "prusament",
    "madeforprusa": "prusament",
    "colorfabb": "colorfabb",
    "fiberlogy": "fiberlogy",
    "add": "addnorth",
}

# Order matters: longer prefixes first.
FAMILIES: tuple[str, ...] = (
    "PETG",
    "PCTG",
    "PET",
    "PLA",
    "ABS",
    "ASA",
    "TPU",
    "TPE",
    "PEBA",
    "PA",
    "PPA",
    "PC",
    "PP",
    "PE",
    "PVA",
    "BVOH",
    "HIPS",
    "PHA",
    "EVA",
    "CPE",
    "PVB",
    "PEI",
    "PEEK",
    "PEKK",
    "PPS",
    "PPSU",
    "PSU",
    "PES",
    "PVDF",
)

FAMILY_ALIASES = {
    "PA6": "PA",
    "PA11": "PA",
    "PA12": "PA",
    "PA66": "PA",
    "PA612": "PA",
    "PAHT": "PA",
    "NYLON": "PA",
    "COPE": "PE",
    "PLA+": "PLA",
    "PLAPLUS": "PLA",
    "ABS+": "ABS",
    "PETG+": "PETG",
    "PCABS": "PC",
    "FLEX": "TPU",
}

TOKEN_SYNONYMS = {
    "+": "plus",
    "carbon": "cf",
    "glass": "gf",
    "hs": "highspeed",
    "hispeed": "highspeed",
    "rapid": "highspeed",
    "translucent": "transparent",
    "clear": "transparent",
}

#: Characters that cannot appear in file names on Windows (and "/" nowhere).
UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

STOP_TOKENS = frozenset({"filament", "filaments", "175", "mm", "1", "75", "the", "3d", "system", "fiber", "fibre", "reinforced"})
WINDOWS_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))})


def norm_brand(brand: str) -> str:
    """Reduce a brand to a comparison key ("eSUN 3D" → "esun")."""
    b = (brand or "").lower().replace("&", "and")
    b = re.sub(r"[^a-z0-9]", "", b)
    for suffix in ("filaments", "filament", "3d"):
        if b.endswith(suffix) and len(b) > len(suffix) + 2:
            b = b[: -len(suffix)]
    return BRAND_ALIASES.get(b, b)


def family_of(material: str) -> str | None:
    """Material family (PLA, PETG, PA …) from a material string."""
    upper = (material or "").upper()
    compact = re.sub(r"[^A-Z0-9+]", "", upper)
    if not compact:
        return None
    if compact in FAMILY_ALIASES:
        return FAMILY_ALIASES[compact]
    for part in (p for p in re.split(r"[^A-Z0-9+]+", upper) if p):
        bare = part.rstrip("+")
        if bare in FAMILY_ALIASES:
            return FAMILY_ALIASES[bare]
        if bare in FAMILIES:
            return bare
    # Longest family that matches at the start ("PETGCF" → PETG, not PET)
    return max((f for f in FAMILIES if compact.startswith(f)), key=len, default=None)


def tokens(text: str) -> list[str]:
    t = (text or "").lower()
    t = re.sub(r"\b[123][.,](75|85|0)\s*mm\b", " ", t)  # diameter strings
    t = t.replace("+", " + ")
    raw = re.findall(r"[a-z0-9]+|\+", t)
    out = []
    for tok in raw:
        tok = TOKEN_SYNONYMS.get(tok, tok)
        if tok in STOP_TOKENS:
            continue
        out.append(tok)
    # merge "high speed" into one token
    joined: list[str] = []
    i = 0
    while i < len(out):
        if out[i] == "high" and i + 1 < len(out) and out[i + 1] == "speed":
            joined.append("highspeed")
            i += 2
            continue
        joined.append(out[i])
        i += 1
    return joined


def name_tokens(name: str, brand: str, material: str) -> frozenset[str]:
    """Tokens of a product name without brand and material family tokens."""
    drop = set(tokens(brand)) | {norm_brand(brand)}
    fam = family_of(material) or family_of(name)
    fam_token = fam.lower() if fam else None
    result = set()
    for tok in tokens(name):
        if tok in drop or tok == fam_token:
            continue
        # material names like "pa6", "pa12" belong to the family
        if fam_token and re.fullmatch(re.escape(fam_token) + r"\d*", tok):
            continue
        # synonyms of the family ("nylon", "flex")
        if FAMILY_ALIASES.get(tok.upper()) == fam:
            continue
        result.add(tok)
    # "PLA+" as material is a product of its own
    if "plus" in tokens(material):
        result.add("plus")
    # take fibre reinforcement from types like "PLA-CF"
    mat = (material or "").lower()
    for fiber in ("cf", "gf"):
        if re.search(r"(^|[^a-z])" + fiber + r"\d*($|[^a-z])", mat):
            result.add(fiber)
    return frozenset(result)


def match_key(brand: str, material: str, name: str) -> tuple[str, str, frozenset[str]] | None:
    fam = family_of(material) or family_of(name)
    if not fam:
        return None
    return (norm_brand(brand), fam, name_tokens(name, brand, material))


def clean_name(text: str) -> str:
    """Preset name that works as a file name: Bambu Studio saves presets as ``<name>.json``."""
    t = re.sub(r"[/\\]", "-", text or "")
    t = re.sub(r"[:|]", " ", t)
    t = re.sub(r'[<>"?*\x00-\x1f]', "", t)
    return re.sub(r"\s+", " ", t).strip().rstrip(". ")


def alias_of(profile_name: str) -> str:
    """Profile name without the " @printer" suffix."""
    return re.sub(r"\s*@.*$", "", profile_name or "").strip()


def norm_alias(profile_name: str) -> str:
    return re.sub(r"[^a-z0-9+]", "", alias_of(profile_name).lower())


def safe_filename(text: str) -> str:
    """File and folder names for Linux and Windows."""
    cleaned = UNSAFE_FILENAME_CHARS.sub("-", text).strip().rstrip(". ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if cleaned.split(".")[0].upper() in WINDOWS_RESERVED:
        cleaned += "_"
    return cleaned or "unnamed"
