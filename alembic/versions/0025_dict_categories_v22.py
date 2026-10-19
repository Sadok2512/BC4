"""Category/subcategory configuration for dict v2.2 (BC1).

Review gate is intentional: no migration can run while unmapped questions remain.
No measurements, decoder rules, reference datasets or template JSON are changed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0025_dict_categories_v22"
down_revision = "0024_dict_templates"
branch_labels = None
depends_on = None


def _seed():
    path = Path(__file__).resolve().parents[2] / "app/dict/config/categories_v22.json"
    return json.loads(path.read_text())


def _canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def upgrade():
    # Check before ANY DDL or DML, including on PostgreSQL's transactional DDL.
    from app.dict.category_mapping import validate_seed
    seed = _seed()
    validate_seed(seed)
    _upgrade_schema(seed)


def _upgrade_schema(seed):
    """Schema/data operation separately exercisable inside a rolled-back test schema."""
    db = op.get_bind()
    templates = [dict(r) for r in db.execute(sa.text(
        "SELECT category_id,entries,revision FROM dict_template ORDER BY category_id"
    )).mappings()]
    if _canonical_hash(templates) != seed["template_source_sha256"]:
        raise ValueError("Template configuration changed since review; refresh links before migration")
    current_entries = {(t["category_id"], e["id"]) for t in templates for e in t["entries"]}
    for link in seed["template_links"]:
        if (link["template_category_id"], link["entry_id"]) not in current_entries:
            raise ValueError("Template entry missing; no speculative link will be created")

    # Keep the actual installation's old configuration, not a fabricated downgrade seed.
    op.create_table("dict_v22_backup",
        sa.Column("name", sa.String(), primary_key=True),
        sa.Column("payload", JSONB(), nullable=False))
    for table in ("dict_category", "dict_category_map", "dict_template"):
        rows = [dict(r) for r in db.execute(sa.text(f"SELECT * FROM {table}")).mappings()]
        db.execute(sa.text("INSERT INTO dict_v22_backup VALUES (:name,CAST(:payload AS jsonb))"),
                   {"name": table, "payload": json.dumps(rows, default=str)})

    op.add_column("dict_category", sa.Column("tech", sa.String(), nullable=False, server_default="BOTH"))
    op.create_check_constraint("ck_dict_category_tech", "dict_category", "tech IN ('LTE','NR','BOTH')")
    db.execute(sa.text("UPDATE dict_category SET position=99 WHERE id='autres'"))
    for category in seed["categories"]:
        db.execute(sa.text("""
          INSERT INTO dict_category(id,label,position,tech) VALUES (:id,:label,:position,:tech)
          ON CONFLICT(id) DO UPDATE SET label=excluded.label,position=excluded.position,tech=excluded.tech
        """), category)
    op.create_table("dict_subcategory",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("category_id", sa.String(), sa.ForeignKey("dict_category.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("category_id", "code", name="uq_dict_subcategory_code"),
        sa.UniqueConstraint("category_id", "position", name="uq_dict_subcategory_position"),
        sa.UniqueConstraint("id", "category_id", name="uq_dict_subcategory_parent"))
    for sub in seed["subcategories"]:
        db.execute(sa.text("INSERT INTO dict_subcategory VALUES (:id,:category_id,:code,:label,:position)"), sub)

    # The v2.1 composite PK cannot express event-specific sibling fields. Replace it,
    # preserving its exact original rows for downgrade in dict_v22_backup.
    op.drop_table("dict_category_map")
    op.create_table("dict_category_map",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("technology", sa.String(), nullable=False),
        sa.Column("path_prefix", sa.Text(), nullable=False),
        sa.Column("category_id", sa.String(), sa.ForeignKey("dict_category.id"), nullable=False),
        sa.Column("subcategory_id", sa.String(), nullable=True),
        sa.Column("discriminator", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("note", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["subcategory_id", "category_id"],
                                ["dict_subcategory.id", "dict_subcategory.category_id"],
                                name="fk_dict_map_subcategory_parent"),
        sa.UniqueConstraint("technology", "path_prefix", "discriminator", name="uq_dict_map_path_discriminator"),
        sa.CheckConstraint("technology IN ('LTE','NR','BOTH')", name="ck_dict_map_technology"),
        sa.CheckConstraint("jsonb_typeof(discriminator)='object'", name="ck_dict_map_discriminator"),
        sa.CheckConstraint("(category_id='autres' AND subcategory_id IS NULL) OR "
                           "(category_id<>'autres' AND subcategory_id IS NOT NULL)", name="ck_dict_map_subcategory"))
    for row in seed["maps"]:
        db.execute(sa.text("""
          INSERT INTO dict_category_map(technology,path_prefix,category_id,subcategory_id,discriminator,note)
          VALUES (:technology,:path_prefix,:category_id,:subcategory_id,CAST(:discriminator AS jsonb),:note)
        """), dict(row, discriminator=json.dumps(row["discriminator"])))

    # Existing templates can span several subcategories. Link their real JSON row IDs
    # without rewriting entries, labels, formulas, references or their revision.
    op.create_table("dict_template_subcategory",
        sa.Column("template_category_id", sa.String(), sa.ForeignKey("dict_template.category_id"), primary_key=True),
        sa.Column("entry_id", sa.String(), primary_key=True),
        sa.Column("subcategory_id", sa.String(), sa.ForeignKey("dict_subcategory.id"), primary_key=True),
        sa.Column("note", sa.Text(), nullable=False))
    for link in seed["template_links"]:
        db.execute(sa.text("INSERT INTO dict_template_subcategory VALUES (:template_category_id,:entry_id,:subcategory_id,:note)"), link)

    # User-approved template references; retain every entry and absent canonical path.
    for update in seed.get("template_updates", []):
        entries = next(t['entries'] for t in templates if t['category_id']==update['category_id'])
        entry = next(e for e in entries if e['id']==update['entry_id'])
        entry['parameters'] = update['parameters']
        entry['reason'] = ('Vue événement × couche : lot ultérieur.' if entry['id']=='layering-connected-03'
                           else 'Comptage de SCell : lot ultérieur.' if entry['id']=='mimo-ca-04' else None)
        if entry['id']=='layering-connected-05': entry['label']='a5-Threshold1 / 2'
    for template in templates:
        db.execute(sa.text("UPDATE dict_template SET entries=CAST(:entries AS jsonb),revision=revision+1 WHERE category_id=:category_id"),
                   dict(template,entries=json.dumps(template['entries'])))
    _correct_flags(db)


def _correct_flags(db):
    # Actual row flags are saved; payload values/identities are never copied.
    if not sa.inspect(db).has_table('param_occurrence'):
        return  # isolated configuration-only test schema
    identifiers = ['systemInformationBlockType1/cellAccessRelatedInfo/cellIdentity', 'systemInformationBlockType1/cellAccessRelatedInfo/plmn-IdentityList/[*]/plmn-Identity/mcc', 'systemInformationBlockType1/cellAccessRelatedInfo/plmn-IdentityList/[*]/plmn-Identity/mnc', 'systemInformationBlockType1/cellAccessRelatedInfo/trackingAreaCode']
    predicate = "regexp_replace(path, '\\[[0-9]+\\]', '[*]', 'g') = ANY(:paths)"
    predicate = "message='SystemInformationBlockType1' AND (" + predicate + ")"
    target = "(" + predicate + " OR path LIKE '%/logicalChannelConfig/%/logicalChannelGroup')"
    rows = [dict(r) for r in db.execute(sa.text('SELECT id,is_identifier FROM param_occurrence WHERE '+target), {'paths':identifiers}).mappings()]
    db.execute(sa.text("INSERT INTO dict_v22_backup VALUES ('identifier_flags',CAST(:payload AS jsonb))"), {'payload':json.dumps(rows,default=str)})
    db.execute(sa.text('UPDATE param_occurrence SET is_identifier=true WHERE NOT COALESCE(is_identifier,false) AND '+predicate), {'paths':identifiers})
    db.execute(sa.text("UPDATE param_occurrence SET is_identifier=false WHERE is_identifier=true AND path LIKE '%/logicalChannelConfig/%/logicalChannelGroup'"))


def downgrade():
    db = op.get_bind()
    backups = {r[0]: r[1] for r in db.execute(sa.text("SELECT name,payload FROM dict_v22_backup"))}
    op.drop_table("dict_template_subcategory")
    op.drop_table("dict_category_map")
    op.drop_table("dict_subcategory")
    # Do not destroy category rows referenced by templates created after upgrade.
    old_ids = [r["id"] for r in backups["dict_category"]]
    db.execute(sa.text("DELETE FROM dict_category WHERE NOT (id=ANY(:ids))"), {"ids": old_ids})
    op.drop_constraint("ck_dict_category_tech", "dict_category", type_="check")
    op.drop_column("dict_category", "tech")
    for row in backups["dict_category"]:
        db.execute(sa.text("UPDATE dict_category SET label=:label,position=:position WHERE id=:id"), row)
    op.create_table("dict_category_map",
        sa.Column("technology", sa.String(), primary_key=True),
        sa.Column("path_prefix", sa.String(), primary_key=True),
        sa.Column("category_id", sa.String(), sa.ForeignKey("dict_category.id"), nullable=False))
    for row in backups["dict_category_map"]:
        db.execute(sa.text("INSERT INTO dict_category_map VALUES (:technology,:path_prefix,:category_id)"), row)
    for row in backups.get('dict_template', []):
        db.execute(sa.text("UPDATE dict_template SET entries=CAST(:entries AS jsonb),revision=:revision WHERE category_id=:category_id"),dict(row,entries=json.dumps(row['entries'])))
    for row in backups.get('identifier_flags', []):
        db.execute(sa.text("UPDATE param_occurrence SET is_identifier=:is_identifier WHERE id=:id"),row)
    op.drop_table("dict_v22_backup")
