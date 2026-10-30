from app.kpi.map_cell_links import enrich_radio_links


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self.rows


class _Db:
    def __init__(self, identities, refs, anchors=None):
        self.identities = identities
        self.refs = refs
        self.anchors = anchors or []
        self.calls = []

    def execute(self, statement, params):
        sql = str(statement)
        self.calls.append((sql, params))
        if "WITH targets AS" in sql:
            return _Result(self.anchors)
        if "FROM nmf_cell_identity" in sql:
            return _Result(self.identities)
        return _Result(self.refs)


def test_exact_identity_nearest_candidate_and_nr_anchor_require_serving():
    identities = [
        {"seq": 20, "system": 7, "cell_type": 2, "cell_arfcn": 1675, "cell_pci": 215},
    ]
    anchors = [
        {"seq": 20, "system": 9, "cell_type": 199, "cell_arfcn": 643392, "cell_pci": 7},
    ]
    refs = [
        {"system": 7, "arfcn": 1675, "pci": 215, "reference_channel": 1675, "cell_ref_id": "lte-far",
         "site_id": "s2", "site_name": None, "lat": 50.2, "lng": 3.0},
        {"system": 7, "arfcn": 1675, "pci": 215, "reference_channel": 1675, "cell_ref_id": "lte-near",
         "site_id": "s1", "site_name": "near", "lat": 50.0001, "lng": 3.0},
        {"system": 9, "arfcn": 643392, "pci": 7, "reference_channel": 643392, "cell_ref_id": "nr",
         "site_id": "s1", "site_name": "anchor", "lat": 50.0002, "lng": 3.0},
    ]
    point = {"seq": 20, "_second": 10, "lat": 50.0, "lng": 3.0,
             "serving_cell_ref_id": "serving"}
    db = _Db(identities, refs, anchors)

    enrich_radio_links(db, "project-a", "capture-a", [point])

    assert point["neighbour_links"][0]["cell_ref_id"] == "lte-near"
    assert point["neighbour_links"][0]["candidate_count"] == 2
    assert point["neighbour_links"][0]["max_distance_m"] == 25_000.0
    assert point["neighbour_links"][0]["reference_channel"] == 1675
    assert point["neighbour_links"][0]["confidence"] == "radio_arfcn_pci_nearest_within_25000m"
    assert point["nr_anchor_link"]["cell_ref_id"] == "nr"
    assert point["nr_anchor_link"]["reference_channel"] == 643392
    assert "_second" not in point
    sql, params = db.calls[0]
    assert "project_id=:pid AND capture_id=:cap" in sql
    assert params["pid"] == "project-a" and params["cap"] == "capture-a"
    refs_sql = db.calls[1][0]
    assert "r.earfcn=w.arfcn" in refs_sql
    assert "r.nr_arfcn=w.arfcn" in refs_sql
    assert "band_mhz" not in refs_sql


def test_no_guess_outside_radius_and_no_anchor_without_lte_serving_proof():
    identities = [
        {"seq": 30, "system": 7, "cell_type": 1, "cell_arfcn": 900, "cell_pci": 1},
        {"seq": 30, "system": 9, "cell_type": 199, "cell_arfcn": 640000, "cell_pci": 7},
    ]
    refs = [
        {"system": 7, "arfcn": 900, "pci": 1, "cell_ref_id": "too-far",
         "site_id": None, "site_name": None, "lat": 51.0, "lng": 3.0},
        {"system": 9, "arfcn": 640000, "pci": 7, "cell_ref_id": "nr",
         "site_id": None, "site_name": None, "lat": 50.0, "lng": 3.0},
    ]
    point = {"seq": 30, "lat": 50.0, "lng": 3.0}

    enrich_radio_links(_Db(identities, refs), "project-a", "capture-a", [point])

    assert point["neighbour_links"] == []
    assert point["nr_anchor_link"] is None
