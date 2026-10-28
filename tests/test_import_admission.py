from app.services import import_admission as admission


def test_uses_lower_cgroup_headroom(tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemAvailable:       8388608 kB\n")
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    (cgroup / "memory.max").write_text(str(3 * admission.MIB))
    (cgroup / "memory.current").write_text(str(admission.MIB))
    assert min(
        admission._memavailable_bytes(meminfo),
        admission._cgroup_available_bytes(cgroup),
    ) == 2 * admission.MIB


def test_admission_rechecks_memory_and_oversize_runs_alone(monkeypatch):
    values = iter((5000, 5000, 300))
    monkeypatch.setattr(admission, "available_memory_mb", lambda: next(values))
    monkeypatch.setattr(admission.settings, "import_reserved_mb", 4096)
    monkeypatch.setattr(admission.settings, "import_memory_margin_mb", 512)
    monkeypatch.setattr(admission, "estimate_memory_mb", lambda *_: 1000)
    assert admission.decide(1, "deep", running=1).decision == "wait"
    solo = admission.decide(1, "deep", running=0)
    assert (solo.decision, solo.reason) == ("start", "oversize_solo")
    guarded = admission.decide(1, "deep", running=0)
    assert (guarded.decision, guarded.reason) == ("wait", "below_margin")


def test_affine_memory_estimate_has_fixed_base(monkeypatch):
    monkeypatch.setattr(admission.settings, "import_memory_base_mb_deep", 500.0)
    monkeypatch.setattr(admission.settings, "import_memory_slope_mb_per_mib_deep", 50.0)
    assert admission.estimate_memory_mb(0, "deep") == 500
    assert admission.estimate_memory_mb(10 * admission.MIB, "deep") == 1000
