"""Contrats unitaires de la suppression de capture et de sa finalisation."""
from app.services.capture_delete import ALL_CAPTURE_DATA, MIN_REASON_LENGTH
from app.services.populate_measurements import stable_measurement_id


def test_measurement_identity_is_stable_and_capture_scoped():
    first = stable_measurement_id("TEST-PROJECT", "a4b0c321c52e", 42)
    assert first == stable_measurement_id("TEST-PROJECT", "a4b0c321c52e", 42)
    assert first != stable_measurement_id("TEST-PROJECT", "a4b0c321c52e", 43)
    assert first != stable_measurement_id("TEST-OTHER", "a4b0c321c52e", 42)
    assert first.startswith("mp-nmf-")


def test_delete_inventory_includes_native_and_indirect_data():
    assert "nmf_event_light_native" in ALL_CAPTURE_DATA
    assert "nmf_metric_value" in ALL_CAPTURE_DATA
    assert "param_occurrence" in ALL_CAPTURE_DATA
    assert MIN_REASON_LENGTH == 10
