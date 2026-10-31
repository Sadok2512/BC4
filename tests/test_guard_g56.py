from scripts.guards import G56_proven_links as guard


def _point(confidence, method=None):
    return {
        "confidence": confidence,
        "link_method": method,
        "probable_serving_cell_ref_id": (
            "probable-cell" if confidence == "probable" else None
        ),
    }


def _payload(points):
    return {"map_points": points, "total_points": len(points)}


def test_g56_passes_only_with_both_content_thresholds(monkeypatch, capsys):
    def fetch(_base, _token, _project, capture):
        if capture == guard.DEFAULT_PROVEN_CAPTURE:
            return _payload([
                _point("proven", "earfcn_pci")
                for _ in range(guard.EXPECTED_PROVEN)
            ])
        return _payload([_point("probable") for _ in range(guard.MIN_PROBABLE)])

    monkeypatch.setattr(guard, "_fetch_map", fetch)
    assert guard.main(["--base-url", "http://disposable/api", "--token", "test"]) == 0
    output = capsys.readouterr().out
    assert "proven_marked=199" in output
    assert "probable_serving=4435" in output
    assert "G56 VERDICT=PASS" in output


def test_g56_fails_when_one_proven_marker_is_missing(monkeypatch, capsys):
    def fetch(_base, _token, _project, capture):
        if capture == guard.DEFAULT_PROVEN_CAPTURE:
            points = [_point("proven", "earfcn_pci") for _ in range(198)]
            points.append(_point(None))
            return _payload(points)
        return _payload([_point("probable") for _ in range(guard.MIN_PROBABLE)])

    monkeypatch.setattr(guard, "_fetch_map", fetch)
    assert guard.main(["--base-url", "http://disposable/api", "--token", "test"]) == 1
    assert "G56 VERDICT=FAIL reason=proven_serving_regression" in capsys.readouterr().out


def test_g56_fails_below_probable_floor(monkeypatch, capsys):
    def fetch(_base, _token, _project, capture):
        if capture == guard.DEFAULT_PROVEN_CAPTURE:
            return _payload([
                _point("proven", "earfcn_pci")
                for _ in range(guard.EXPECTED_PROVEN)
            ])
        return _payload([_point("probable") for _ in range(guard.MIN_PROBABLE - 1)])

    monkeypatch.setattr(guard, "_fetch_map", fetch)
    assert guard.main(["--base-url", "http://disposable/api", "--token", "test"]) == 1
    assert "G56 VERDICT=FAIL reason=probable_serving_regression" in capsys.readouterr().out


def test_g56_fails_closed_on_http_error(monkeypatch, capsys):
    def fail(*_args):
        raise RuntimeError("http_status=500")

    monkeypatch.setattr(guard, "_fetch_map", fail)
    assert guard.main(["--base-url", "http://disposable/api", "--token", "test"]) == 1
    assert "G56 VERDICT=FAIL reason=map_unavailable" in capsys.readouterr().out


def test_g56_requires_url_and_token(capsys):
    assert guard.main(["--token", "test"]) == 2
    assert "reason=missing_base_url" in capsys.readouterr().out
