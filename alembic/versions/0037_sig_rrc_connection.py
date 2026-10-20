"""Add rrc_connection to signaling_procedure.type CHECK."""
from alembic import op

revision = '0037_sig_rrc_connection'
down_revision = '0036_signaling_procedure'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE signaling_procedure DROP CONSTRAINT signaling_procedure_type_check')
    op.execute("""ALTER TABLE signaling_procedure ADD CONSTRAINT signaling_procedure_type_check
      CHECK(type IN ('rrc_setup','rrc_connection','ho','call','data_session','attach','bearer','reestablishment'))""")


def downgrade():
    op.execute('ALTER TABLE signaling_procedure DROP CONSTRAINT signaling_procedure_type_check')
    op.execute("""ALTER TABLE signaling_procedure ADD CONSTRAINT signaling_procedure_type_check
      CHECK(type IN ('rrc_setup','ho','call','data_session','attach','bearer','reestablishment'))""")
