from app.nmf_decoder.classification import (
    RADIO_KPI_CODES,
    classification_evidence,
    classify_other,
)


THROUGHPUT = {
    "DRATE", "MACRATE", "MACRATEU", "PDCPRATED", "PDCPRATEU",
    "PHRATE", "PHRATEU", "PPPRATE", "RLCRATE", "RLCRATEU",
}
MEASUREMENT = {
    "BSR", "CI", "CSI", "DCI", "MACI", "MIMOMEAS", "NLIST",
    "PCHI", "PLAID", "PLAISUM", "PLAIU", "PMI", "SCELL",
    "SCELLMOD", "TAD",
}


def test_phase1_covers_only_the_25_audited_radio_kpi_types():
    assert RADIO_KPI_CODES == THROUGHPUT | MEASUREMENT
    assert len(RADIO_KPI_CODES) == 25
    for code in THROUGHPUT:
        assert classify_other(code, "other") == "throughput"
    for code in MEASUREMENT:
        assert classify_other(code, "other") == "measurement"


def test_classification_does_not_claim_structure_fields_or_nff259():
    for code in RADIO_KPI_CODES:
        evidence = classification_evidence(code)
        assert evidence.type_recognized is True
        assert evidence.structure_decoded == "not_asserted"
        assert evidence.fields_validated == "not_asserted"
        assert evidence.nff_259_certified is False


def test_unknown_and_upstream_categories_are_preserved():
    evidence = classification_evidence("UNPROVEN")
    assert evidence.type_recognized is False
    assert evidence.category == "other"
    assert classify_other("UNPROVEN", "other") == "other"
    assert classify_other("PHRATE", "custom") == "custom"
    assert classify_other("PHRATE", None) == "signalling"
