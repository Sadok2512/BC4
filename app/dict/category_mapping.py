"""dict v2.2 exact-path configuration primitives shared by catalogue and selectors.

Categories use exact ASN.1 segment prefixes and proven discriminators, never
parameter display names. Unresolved paths return None, never implicit Autres.
"""
from __future__ import annotations

import re
from typing import Any

_INDEX = re.compile(r"\[\d+\]")
_PADDING = re.compile(r"(?:spare\d*|dummy|reserved)")


def normalized_path(path: str) -> str:
    """Preserve CHOICE alternatives. Only SEQUENCE OF element indices normalize."""
    return "/".join("[*]" if _INDEX.fullmatch(part) else part for part in path.split("/"))


# Approved IE boundaries: message wrappers do not participate in classification.
_IE_ANCHORS = frozenset({
    'radioResourceConfigDedicated', 'measConfig', 'mac-MainConfig',
    'physicalConfigDedicated', 'CellGroupConfig', 'spCellConfigDedicated',
    'mac-CellGroupConfig', 'physicalCellGroupConfig', 'rlc-BearerToAddModList',
    'srb-ToAddModList', 'drb-ToAddModList',
})


def mapping_path(path: str) -> str:
    parts = normalized_path(path).split('/')
    indices = [i for i, part in enumerate(parts) if part in _IE_ANCHORS]
    return '/'.join(parts[max(indices):]) if indices else '/'.join(parts)


def identifier_path_rule(path: str) -> str | None:
    """User-approved R2, applied to ASN.1 path segments, not display labels."""
    parts = [p for p in normalized_path(path).split('/') if p != '[*]']
    if not parts:
        return None
    # Release suffixes belong to the ASN.1 field version, not its semantic name.
    names = [re.sub(r'-(?:r|v)[0-9]+$', '', p) for p in parts]
    field = names[-1]
    if field == 'logicalChannelGroup':
        return None
    if 'traceReference' in names:
        return 'R2: traceReference subtree'
    if field.endswith(('Id', 'ID', '-Identity')) or field in {
        'mcc', 'mnc', 'cellIdentity', 'trackingAreaCode', 'physCellId',
        'scramblingID', 'scramblingID0', 'scramblingID1', 'sequenceId', 'hoppingId',
    }:
        return 'R2: ASN.1 identifier field'
    if field == 'start' and any(p in {'physCellIdRange', 'interFreqExcludedCellList', 'intraFreqExcludedCellList'} for p in names[:-1]):
        return 'R2: PCI range start'
    if 'measIdToAddModListExt' in names:
        return 'R2: extended measurement identifiers'
    return None


def excluded_field(path: str, is_identifier: bool = False) -> bool:
    """Exactly the user-approved exclusions a+b. No BIT STRING/constant-value rule."""
    return bool(is_identifier or _PADDING.fullmatch(path.rsplit("/", 1)[-1]) or path in ("systemFrameNumber", "mib/systemFrameNumber"))


def resolve_mapping(
    technology: str, path: str, discriminators: dict[str, Any] | None, mappings: list[dict],
) -> dict | None:
    path = mapping_path(path)
    discriminators = discriminators or {}
    candidates = []
    for row in mappings:
        prefix = mapping_path(row["path_prefix"])
        if row["technology"] not in (technology, "BOTH"):
            continue
        if path != prefix and not path.startswith(prefix + "/"):
            continue
        if any(key not in discriminators or discriminators[key] != value for key, value in row["discriminator"].items()):
            continue
        # Specific path first, then narrower discriminator / technology.
        score = (len(prefix.split("/")), len(row["discriminator"]), row["technology"] == technology)
        candidates.append((score, row))
    if not candidates:
        return None
    best = max(score for score, _ in candidates)
    winners = [row for score, row in candidates if score == best]
    if len({(r["category_id"], r["subcategory_id"]) for r in winners}) != 1:
        raise ValueError(f"Ambiguous category configuration: {technology} {path}")
    return winners[0]


def validate_seed(seed: dict, *, require_reviewed: bool = True) -> None:
    if require_reviewed and (
        seed["status"] != "APPROVED"
        or seed["unresolved"]
        or seed["template_unresolved"]
    ):
        raise ValueError("dict v2.2 review pending: resolve audit/dict-v2.2/unmapped.csv and template-unmapped.csv before migration")
    categories = {c["id"]: c for c in seed["categories"]}
    subs = {s["id"]: s for s in seed["subcategories"]}
    if len(categories) != len(seed["categories"]) or len(subs) != len(seed["subcategories"]):
        raise ValueError("Duplicate taxonomy identity")
    if categories.get("autres", {}).get("position") != 99:
        raise ValueError("Autres must have position 99")
    for c in categories.values():
        if c["tech"] not in ("LTE", "NR", "BOTH"):
            raise ValueError("Invalid category technology")
    for s in subs.values():
        if s["category_id"] not in categories:
            raise ValueError("Unknown subcategory parent")
    identities = set()
    for row in seed["maps"]:
        prefix = row["path_prefix"]
        if row["technology"] not in ("LTE", "NR", "BOTH"):
            raise ValueError("Invalid mapping technology")
        if not prefix or prefix != normalized_path(prefix):
            raise ValueError("Expected normalized exact ASN.1 path")
        for segment in prefix.split("/"):
            if segment in ("", ".", "..") or (segment != "[*]" and any(c in segment for c in "*^$?{}()|\\")):
                raise ValueError("Regex/glob not allowed in ASN.1 prefixes")
        if row["category_id"] not in categories:
            raise ValueError("Unknown mapping category")
        if row["category_id"] == "autres":
            if row["subcategory_id"] is not None or not row.get("note"):
                raise ValueError("Autres requires explicit reason and no invented subcategory")
        elif row["subcategory_id"] not in subs or subs[row["subcategory_id"]]["category_id"] != row["category_id"]:
            raise ValueError("Subcategory belongs to another category")
        import json
        identity = (row["technology"], prefix, json.dumps(row["discriminator"], sort_keys=True))
        if identity in identities:
            raise ValueError("Duplicate mapping")
        identities.add(identity)
    for link in seed["template_links"]:
        if link["subcategory_id"] not in subs:
            raise ValueError("Unknown template subcategory")
