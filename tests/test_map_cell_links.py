from app.kpi.map_cell_links import (
    MAX_NEIGHBOUR_LINKS_PER_POINT,
    _nr_arfcn_to_band_mhz,
    enrich_probable_neighbour_nr_links,
    enrich_radio_links,
)


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


class _ProbableDb:
    def __init__(self, lte, nr, refs):
        self.lte = lte
        self.nr = nr
        self.refs = refs
        self.calls = []

    def execute(self, statement, params):
        sql = str(statement)
        self.calls.append((sql, params))
        if "WITH targets AS" in sql:
            return _Result(self.nr)
        if "i.system=7" in sql:
            return _Result(self.lte)
        if "FROM cell_ref" in sql:
            return _Result(self.refs)
        raise AssertionError(sql)


def test_probable_links_keep_proven_cap_strongest_and_prefer_pscell():
    lte = [
        {
            "seq": 20, "system": 7, "cell_type": 2, "cell_arfcn": 1300,
            "cell_pci": pci, "cell_index": 1100 + pci, "strength": -60 - pci,
        }
        for pci in range(1, 8)
    ]
    nr = [
        {"seq": 20, "system": 9, "cell_type": 1000, "cell_arfcn": 643392,
         "cell_pci": 81, "cell_index": 2081, "strength": -50},
        {"seq": 20, "system": 9, "cell_type": 199, "cell_arfcn": 643392,
         "cell_pci": 80, "cell_index": 2080, "strength": -90},
    ]
    refs = [
        {"id": f"lte-{pci}", "band_mhz": 1800, "pci": pci,
         "site_id": "lte-site", "site_name": "LTE", "system": 7,
         "lat": 50.0001, "lng": 3.0}
        for pci in range(1, 8)
    ] + [
        {"id": "nr-pscell", "band_mhz": 3500, "pci": 80,
         "site_id": "nr-site", "site_name": "NR PSCell", "system": 9,
         "lat": 50.0002, "lng": 3.0},
        {"id": "nr-neighbour", "band_mhz": 3500, "pci": 81,
         "site_id": "nr-site", "site_name": "NR neighbour", "system": 9,
         "lat": 50.0003, "lng": 3.0},
    ]
    proven = {
        "system": "LTE", "arfcn": 1300, "pci": 1, "cell_type": 2,
        "cell_ref_id": "proven", "confidence": "radio_arfcn_pci_unique",
    }
    point = {
        "seq": 20, "lat": 50.0, "lng": 3.0,
        "probable_serving_cell_ref_id": "serving",
        "neighbour_links": [proven], "nr_anchor_link": None,
    }
    unproven_point = {
        "seq": 20, "lat": 50.0, "lng": 3.0,
        "probable_serving_cell_ref_id": "serving",
        "neighbour_links": [], "nr_anchor_link": None,
    }

    db = _ProbableDb(lte, nr, refs)
    enrich_probable_neighbour_nr_links(
        db, "project-a", "capture-a", [point, unproven_point], {20: 10}
    )

    assert point["neighbour_links"][0] is proven
    assert len(point["neighbour_links"]) == MAX_NEIGHBOUR_LINKS_PER_POINT == 1
    assert all(link["confidence"] == "probable" for link in point["neighbour_links"][1:])
    assert [link["pci"] for link in unproven_point["neighbour_links"]] == [1]
    assert point["nr_anchor_link"]["cell_type"] == 199
    assert point["nr_anchor_link"]["cell_ref_id"] == "nr-pscell"
    assert point["nr_anchor_link"]["confidence"] == "probable"
    refs_sql = next(sql for sql, _ in db.calls if "FROM cell_ref" in sql)
    assert "geom && ST_MakeEnvelope" in refs_sql


def test_probable_nr_never_replaces_proven_anchor_and_scopes_every_query():
    anchor = {"cell_ref_id": "proven-nr", "confidence": "radio_arfcn_pci_unique"}
    point = {
        "seq": 30, "lat": 50.0, "lng": 3.0, "serving_cell_ref_id": "lte",
        "neighbour_links": [], "nr_anchor_link": anchor,
    }
    db = _ProbableDb([], [{
        "seq": 30, "system": 9, "cell_type": 199, "cell_arfcn": 643392,
        "cell_pci": 80, "cell_index": 2080, "strength": -70,
    }], [{
        "id": "nr-probable", "band_mhz": 3500, "pci": 80,
        "site_id": "nr", "site_name": "NR", "system": 9,
        "lat": 50.0001, "lng": 3.0,
    }])

    enrich_probable_neighbour_nr_links(db, "project-a", "capture-a", [point], {30: 12})

    assert point["nr_anchor_link"] is anchor
    assert _nr_arfcn_to_band_mhz(643392) == (3500,)
    scoped = [sql for sql, params in db.calls if "nmf_" in sql]
    assert scoped and all("project_id=:pid" in sql and "capture_id=:cap" in sql for sql in scoped)
