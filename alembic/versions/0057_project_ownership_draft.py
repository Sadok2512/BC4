"""DRAFT ONLY — L1 project owner and visibility.

This revision is intentionally blocked until Codex67 confirms the admin email
and the owner/visibility of the six archived demonstration projects. It has
never been applied to the live database.
"""
from alembic import op
import sqlalchemy as sa

revision = "0057_project_ownership"
down_revision = "0056_range_violations"
branch_labels = None
depends_on = None

PENDING = "__PENDING_CODEX67_CONFIRMATION__"
CODEX67_ADMIN_EMAIL = PENDING

# id -> (owner email, visibility, target status or None)
# No owner or visibility is guessed for the six archived projects.
PROJECT_ASSIGNMENTS = {
    "134af70a06eb": (CODEX67_ADMIN_EMAIL, "public", None),       # TEST2
    "4b7bfd50ddb6": (CODEX67_ADMIN_EMAIL, "public", None),       # Test_3
    "ea93767bd734": (CODEX67_ADMIN_EMAIL, "public", None),       # Test_outdoor
    "fa9301f2f3fe": ("signaling-reader@bc4.local", "public", None),  # One_Log
    "idf-t3-2026": (PENDING, PENDING, "archived"),
    "lille-indoor-2026": (PENDING, PENDING, "archived"),
    "lyon-drive-2026": (PENDING, PENDING, "archived"),
    "marseille-5g-2026": (PENDING, PENDING, "archived"),
    "national-2026": (PENDING, PENDING, "archived"),
    "rennes-lte-2026": (PENDING, PENDING, "archived"),
}


def _validate_decisions() -> None:
    pending = [pid for pid, (owner, visibility, _status) in PROJECT_ASSIGNMENTS.items()
               if owner == PENDING or visibility == PENDING]
    if CODEX67_ADMIN_EMAIL == PENDING or pending:
        raise RuntimeError(
            "0057 DRAFT blocked: Codex67 must confirm the admin email and "
            f"owner/visibility for projects {pending}"
        )


def upgrade() -> None:
    _validate_decisions()  # fail before the first DDL statement
    bind = op.get_bind()
    op.add_column("projects", sa.Column("owner_id", sa.String(), nullable=True))
    op.add_column("projects", sa.Column("visibility", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_projects_owner_id_app_user", "projects", "app_user", ["owner_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_projects_visibility", "projects", "visibility IN ('private','public')"
    )

    for project_id, (email, visibility, status) in PROJECT_ASSIGNMENTS.items():
        owner_id = bind.execute(
            sa.text("SELECT id FROM app_user WHERE email=:email AND active=true"),
            {"email": email},
        ).scalar_one_or_none()
        if owner_id is None:
            raise RuntimeError(f"0057 owner account unavailable for project {project_id}")
        result = bind.execute(
            sa.text("""UPDATE projects SET owner_id=:owner_id, visibility=:visibility,
                       status=COALESCE(:status,status) WHERE id=:project_id"""),
            {"owner_id": owner_id, "visibility": visibility,
             "status": status, "project_id": project_id},
        )
        if result.rowcount != 1:
            raise RuntimeError(f"0057 expected project missing: {project_id}")

    missing = bind.execute(
        sa.text("SELECT count(*) FROM projects WHERE owner_id IS NULL OR visibility IS NULL")
    ).scalar_one()
    if missing:
        raise RuntimeError(f"0057 refuses to finish: {missing} project(s) lack owner/visibility")

    op.alter_column("projects", "owner_id", nullable=False)
    op.alter_column("projects", "visibility", nullable=False)
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])
    op.create_index("ix_projects_visibility", "projects", ["visibility"])
    # Access policy is deliberately not encoded as an admin bypass here:
    # My/All must use owner/public/share predicates in L1 service code.


def downgrade() -> None:
    op.drop_index("ix_projects_visibility", table_name="projects")
    op.drop_index("ix_projects_owner_id", table_name="projects")
    op.drop_constraint("ck_projects_visibility", "projects", type_="check")
    op.drop_constraint("fk_projects_owner_id_app_user", "projects", type_="foreignkey")
    op.drop_column("projects", "visibility")
    op.drop_column("projects", "owner_id")
