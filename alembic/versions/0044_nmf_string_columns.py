"""Use text storage for NMF documented string fields."""

import re

from alembic import op

revision='0044_nmf_string_columns'
down_revision='0043_kind'
branch_labels=None
depends_on=None
COLS = 'bf_bts_file dl_device_label dn_device_name ei_device_identity ff_file_format_version hv_handler_version hw_hardware_version hw_manufacturer hw_model id_measurement_id mf_map_file product_product_name product_product_version si_subscriber_identity sp_subscriber_phone_number start_date stop_date sw_device_software_version ts_test_script_file caa_phone_number caa_own_phone_number caa_unique_id daa_host_address pac_ip rrcsm_rrc_msg rrcsm_subchannel rrcsm_rrc_data rtpsm_rtp_message rtpsm_rtp_data sipsm_sip_name sipsm_sip_data'.split()


def _restore_numeric_view_casts(view: str) -> str:
    """Restore casts pg_get_viewdef elides while the source columns are numeric.

    ``nmf_metric_value.value`` is a numeric column.  Before this migration the
    documented string fields were (incorrectly) stored as doubles, so
    PostgreSQL removed their explicit casts from the normalized view
    definition.  The casts must be put back before those source columns become
    text, otherwise the heterogeneous VALUES list cannot be recreated.
    """
    for column in COLS:
        reference = rf"\bd\.{re.escape(column)}\b(?!\s*::double precision)"
        view = re.sub(reference, f"d.{column}::double precision", view)
    return view


def upgrade():
    bind = op.get_bind()
    view = bind.exec_driver_sql("SELECT pg_get_viewdef('nmf_metric_value'::regclass, true)").scalar()
    if view:
        view = _restore_numeric_view_casts(view)
    op.execute('DROP VIEW IF EXISTS nmf_metric_value')
    for table in ('nmf_event_deep','nmf_event_light'):
        for col in COLS:
            op.execute(f'ALTER TABLE {table} ALTER COLUMN {col} TYPE text USING {col}::text')
    if view:
        op.execute('CREATE VIEW nmf_metric_value AS ' + view)
def downgrade():
    pass
