"""G43 — reject numeric aggregations declared on non-numeric NFF fields."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.nmf_decoder.schema import schemas


NUMERIC_AGGREGATIONS = frozenset({"sum", "mean", "min", "max"})
NUMERIC_TYPES = frozenset({"int", "float"})


def iter_fields():
    for event, base in schemas().items():
        documents = [("base", base)]
        documents.extend(
            (f"system={system}", variant)
            for system, variant in sorted((base.get("_variants") or {}).items())
        )
        for variant_name, document in documents:
            for field in document.get("header", []):
                yield event, variant_name, "header", field
            for group in document.get("groups", []):
                for field in group.get("fields", []):
                    yield event, variant_name, f"group={group['name']}", field


def main() -> int:
    loaded = schemas()
    examined = 0
    incompatible = []
    for event, variant, scope, field in iter_fields():
        examined += 1
        aggregation = field.get("agg")
        field_type = field.get("type")
        if aggregation in NUMERIC_AGGREGATIONS and field_type not in NUMERIC_TYPES:
            incompatible.append(
                (event, variant, scope, field.get("code"), field_type, aggregation)
            )

    print(f"G43 loaded_schemas={len(loaded)} examined_fields={examined}")
    print("G43 incompatible_fields_begin")
    for event, variant, scope, code, field_type, aggregation in sorted(incompatible):
        print(
            "G43_INCOMPATIBLE "
            f"event={event} variant={variant} scope={scope} code={code} "
            f"type={field_type} aggregation={aggregation}"
        )
    print("G43 incompatible_fields_end")
    verdict = "PASS" if not incompatible else "FAIL"
    print(f"G43 VERDICT={verdict} incompatible={len(incompatible)}")
    return 0 if not incompatible else 1


if __name__ == "__main__":
    raise SystemExit(main())
