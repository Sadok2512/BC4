"""Manual step-1 validation. Real configuration, isolated PostgreSQL schema + rollback."""
import copy
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import engine
from app.dict.category_mapping import excluded_field, normalized_path, resolve_mapping, validate_seed

ROOT = Path(__file__).resolve().parents[1]


def load_migration(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "alembic/versions" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def seed():
    return json.loads((ROOT / "app/dict/config/categories_v22.json").read_text())


def test_only_approved_exclusions():
    for name in ["spare", "spare1", "spare23", "dummy", "reserved"]:
        assert excluded_field("TEST/context/" + name)
    for name in ["systemFrameNumber", "codebookSubsetRestriction", "neighCellConfig",
                 "reservedForOperatorUse", "spare-r15", "dummyValue", "reservedConfig"]:
        assert not excluded_field("TEST/context/" + name)
    assert excluded_field("TEST/anything", True)


def test_exact_prefix_not_name_and_event_specificity():
    def row(path, sub, disc=None, tech="LTE"):
        return dict(technology=tech, path_prefix=path, category_id=sub.split(".")[0],
                    subcategory_id=sub, discriminator=disc or {})
    maps = [
        row("TEST/root", "phy.carrier"),
        row("TEST/root/list/[*]/event/timeToTrigger", "mobility.intra", {"event": "A3"}),
        row("TEST/root/list/[*]/event/timeToTrigger", "mobility.inter", {"event": "A5"}),
    ]
    assert normalized_path("[3]/list/[25]/choice/eventA3") == "[*]/list/[*]/choice/eventA3"
    assert resolve_mapping("LTE", "TEST/root/list/[25]/event/timeToTrigger", {"event": "A3"}, maps)["subcategory_id"] == "mobility.intra"
    assert resolve_mapping("LTE", "TEST/root/list/[2]/event/timeToTrigger", {"event": "A5"}, maps)["subcategory_id"] == "mobility.inter"
    assert resolve_mapping("LTE", "TEST/rooted/timeToTrigger", {}, maps) is None
    assert resolve_mapping("LTE", "TEST/other/timeToTrigger", {"event": "A3"}, maps) is None
    assert resolve_mapping("NR", "TEST/root/timeToTrigger", {}, maps) is None
    with pytest.raises(ValueError, match="Ambiguous"):
        resolve_mapping("LTE", "TEST/root", {}, maps + [row("TEST/root", "mac.sr")])


def test_missing_discriminator_is_not_an_explicit_null():
    maps = [dict(technology="LTE", path_prefix="TEST/x", category_id="phy",
                 subcategory_id="phy.carrier", discriminator={"context": None})]
    assert resolve_mapping("LTE", "TEST/x", {}, maps) is None
    assert resolve_mapping("LTE", "TEST/x", {"context": None}, maps) is not None


def test_every_observed_population_is_accounted_for(seed):
    import csv
    detail = list(csv.DictReader((ROOT / "audit/dict-v2.2/path-populations.csv").open()))
    coverage = list(csv.DictReader((ROOT / "audit/dict-v2.2/path-coverage.csv").open()))
    assert len(detail) == len(coverage)
    for source, claimed in zip(detail, coverage):
        assert source["path"] == claimed["path"]
        assert source["n_occurrences"] == claimed["n_occurrences"]
        if source["origin"] != "network_config":
            assert claimed["state"] == "PRESERVED_ROOT"
            continue
        match = resolve_mapping(source["system"], source["path"],
                                json.loads(source["discriminators"] or "{}"), seed["maps"])
        if claimed["state"] == "MAPPED":
            assert match is not None
            assert match["subcategory_id"] == claimed["subcategory_id"]
        else:
            assert claimed["state"] == "UNRESOLVED"
            assert match is None


def test_seed_consistent_but_review_required(seed):
    validate_seed(seed, require_reviewed=False)
    validate_seed(seed)
    pending = dict(seed, status="REVIEW_REQUIRED")
    with pytest.raises(ValueError, match="review pending"):
        validate_seed(pending)
    assert not seed["unresolved"]
    assert not any(row["category_id"] == "autres" for row in seed["maps"])
    assert {c["position"] for c in seed["categories"]} == set(range(1, 13)) | {99}


def test_regex_configuration_rejected(seed):
    broken = copy.deepcopy(seed)
    broken["maps"][0]["path_prefix"] = "TEST/.*/timeToTrigger"
    with pytest.raises(ValueError, match="Regex"):
        validate_seed(broken, require_reviewed=False)


@pytest.fixture
def schema(monkeypatch):
    with engine.connect() as connection:
        transaction = connection.begin()
        schema_name = "test_dict_v22_" + uuid4().hex
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema_name}"'))
        operations = Operations(MigrationContext.configure(connection))
        old = load_migration("0024_dict_templates")
        monkeypatch.setattr(old, "op", operations)
        old.upgrade()
        # Preserve the exact real template configuration under review, not a reconstructed label mapping.
        templates = json.loads((ROOT / "audit/dict-v2.2/templates-before.json").read_text())
        for template in templates:
            connection.execute(text("UPDATE dict_template SET entries=CAST(:entries AS jsonb),revision=:revision WHERE category_id=:category_id"),
                               dict(template, entries=json.dumps(template["entries"])))
        new = load_migration("0025_dict_categories_v22")
        monkeypatch.setattr(new, "op", operations)
        yield connection, new
        transaction.rollback()


def test_upgrade_gate_before_ddl(schema, seed, monkeypatch):
    connection, migration = schema
    monkeypatch.setattr(migration, "_seed", lambda: dict(seed,status="REVIEW_REQUIRED"))
    with pytest.raises(ValueError, match="review pending"):
        migration.upgrade()
    assert connection.execute(text("SELECT to_regclass('dict_subcategory')")).scalar() is None
    assert connection.execute(text("SELECT to_regclass('dict_v22_backup')")).scalar() is None


def test_schema_roundtrip_constraints_and_templates_unchanged(schema, seed):
    connection, migration = schema
    def snapshot(table):
        return sorted((dict(r) for r in connection.execute(text("SELECT * FROM " + table)).mappings()),
                      key=lambda row: json.dumps(row, sort_keys=True))
    before = {t: snapshot(t) for t in ["dict_category", "dict_category_map", "dict_template"]}
    # Exercise draft DDL inside rollback only; public upgrade remains deliberately gated.
    migration._upgrade_schema(seed)
    assert {r["category_id"] for r in snapshot("dict_template")} == {r["category_id"] for r in before["dict_template"]}
    assert connection.execute(text("SELECT count(*) FROM dict_category_map")).scalar() == len(seed["maps"])
    assert connection.execute(text("SELECT count(*) FROM dict_subcategory")).scalar() == len(seed["subcategories"])
    assert connection.execute(text("SELECT count(*) FROM dict_template_subcategory")).scalar() == len(seed["template_links"])
    assert connection.execute(text("SELECT position FROM dict_category WHERE id='autres'")).scalar() == 99
    assert connection.execute(text("SELECT count(*) FROM dict_category_map WHERE category_id='autres'")).scalar() == 0
    assert connection.execute(text("SELECT count(*) FROM dict_category_map WHERE discriminator <> '{}'::jsonb")).scalar() > 0
    with pytest.raises(IntegrityError):
        with connection.begin_nested():
            connection.execute(text("""INSERT INTO dict_category_map(technology,path_prefix,category_id,subcategory_id,note)
              VALUES ('LTE','TEST/invalid','phy','mac.sr','TEST invalid parent')"""))
    with pytest.raises(IntegrityError):
        with connection.begin_nested():
            connection.execute(text("""INSERT INTO dict_category_map(technology,path_prefix,category_id,subcategory_id,note)
              VALUES ('LTE','TEST/missing','phy',NULL,'TEST missing subcategory')"""))
    migration.downgrade()
    for table, previous in before.items():
        assert snapshot(table) == previous
    assert connection.execute(text("SELECT to_regclass('dict_subcategory')")).scalar() is None


def test_stale_template_review_rejected_before_ddl(schema, seed):
    connection, migration = schema
    connection.execute(text("UPDATE dict_template SET revision=revision+1"))
    with pytest.raises(ValueError, match="changed since review"):
        migration._upgrade_schema(seed)
    assert connection.execute(text("SELECT to_regclass('dict_v22_backup')")).scalar() is None
