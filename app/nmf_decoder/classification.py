"""Evidence-bounded classification for records emitted as ``other``.

This module classifies the *type* of an event only. It deliberately makes no
claim that the record layout or its fields are valid for NFF 2.59: the three
reference files declare 2.59 while the available specification stops at 2.50.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


CLASSIFICATION_VERSION = "1.0.0"
Category = Literal["measurement", "throughput", "other"]


@dataclass(frozen=True)
class ClassificationEvidence:
    category: Category
    type_recognized: bool
    structure_decoded: Literal["not_asserted"] = "not_asserted"
    fields_validated: Literal["not_asserted"] = "not_asserted"
    nff_259_certified: bool = False


_THROUGHPUT_CODES = frozenset(
    {
        "DRATE", "MACRATE", "MACRATEU", "PDCPRATED", "PDCPRATEU",
        "PHRATE", "PHRATEU", "PPPRATE", "RLCRATE", "RLCRATEU",
    }
)

_MEASUREMENT_CODES = frozenset(
    {
        "BSR", "CI", "CSI", "DCI", "MACI", "MIMOMEAS", "NLIST",
        "PCHI", "PLAID", "PLAISUM", "PLAIU", "PMI", "SCELL",
        "SCELLMOD", "TAD",
    }
)

RADIO_KPI_CODES = _THROUGHPUT_CODES | _MEASUREMENT_CODES


def classification_evidence(event_code: str | None) -> ClassificationEvidence:
    """Return type-only evidence without certifying structure or fields."""

    code = event_code or ""
    if code in _THROUGHPUT_CODES:
        return ClassificationEvidence(category="throughput", type_recognized=True)
    if code in _MEASUREMENT_CODES:
        return ClassificationEvidence(category="measurement", type_recognized=True)
    return ClassificationEvidence(category="other", type_recognized=False)


def classify_other(event_code: str | None, category: str | None) -> str:
    """Refine only ``other``; an upstream non-other category always wins."""

    current = category or "signalling"
    if current != "other":
        return current
    return classification_evidence(event_code).category
