from app.routes.signaling import compact_points_payload


def test_compact_points_are_lossless_for_map_content():
    points = [
        dict(seq=11, t_rel_s=1.25, lat=50.1, lng=2.2,
             protocol="RRC LTE", layer="rrc_lte", gps_seq=10, seq_gap=1),
        dict(seq=12, t_rel_s=1.5, lat=50.1, lng=2.2,
             protocol="NAS", layer="nas", gps_seq=10, seq_gap=2),
        dict(seq=13, t_rel_s=2.0, lat=None, lng=None,
             protocol="MAC-RACH", layer="mac", gps_seq=None, seq_gap=None),
    ]
    payload = compact_points_payload(
        "project", "capture", points, len(points), {"indoor": False}, {}, None,
    )
    protocols = payload["protocols"]
    rebuilt = [
        dict(seq=row[0], t_rel_s=row[1], lat=row[2], lng=row[3],
             protocol=protocols[row[4]], gps_seq=row[5], seq_gap=row[6])
        for row in payload["points"]
    ]
    expected = [
        {key: point[key] for key in
         ("seq", "t_rel_s", "lat", "lng", "protocol", "gps_seq", "seq_gap")}
        for point in points
    ]
    assert rebuilt == expected
    assert payload["positioned_count"] == 2
    assert payload["returned"] == payload["total"] == 3
    assert payload["markers"][0][5] == [1, 0, 1, 0, 0]
