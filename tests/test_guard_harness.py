from types import SimpleNamespace

from scripts.guards import run_all


def test_missing_dsn_is_fail_closed(monkeypatch, capsys):
    monkeypatch.delenv("BC4_DSN", raising=False)
    assert run_all.main(["--base-url", "http://127.0.0.1:9182", "--token", "test"]) == 2
    assert "GUARDS VERDICT=FAIL reason=missing_dsn" in capsys.readouterr().out


def test_missing_base_url_is_fail_closed(monkeypatch, capsys):
    monkeypatch.setenv("BC4_DSN", "postgresql://disposable")
    assert run_all.main(["--token", "test"]) == 2
    assert "GUARDS VERDICT=FAIL reason=missing_base_url" in capsys.readouterr().out


def test_missing_token_is_fail_closed(monkeypatch, capsys):
    monkeypatch.setenv("BC4_DSN", "postgresql://disposable")
    monkeypatch.delenv("G51_TOKEN", raising=False)
    assert run_all.main(["--base-url", "http://127.0.0.1:9182"]) == 2
    assert "GUARDS VERDICT=FAIL reason=missing_g51_token" in capsys.readouterr().out


def test_run_accepts_only_zero_exit_and_pass(monkeypatch):
    monkeypatch.setattr(run_all.subprocess, "run", lambda *a, **k: SimpleNamespace(
        stdout="G18b VERDICT=PASS projects=1", returncode=0,
    ))
    verdict, _duration, returncode = run_all._run("G18b", ["guard"])
    assert (verdict, returncode) == ("PASS", 0)


def test_run_nonzero_exit_overrides_printed_pass(monkeypatch):
    monkeypatch.setattr(run_all.subprocess, "run", lambda *a, **k: SimpleNamespace(
        stdout="G24 VERDICT=PASS", returncode=1,
    ))
    verdict, _duration, returncode = run_all._run("G24", ["guard"])
    assert (verdict, returncode) == ("FAIL", 1)


def test_run_missing_verdict_is_fail(monkeypatch, capsys):
    monkeypatch.setattr(run_all.subprocess, "run", lambda *a, **k: SimpleNamespace(
        stdout="silent guard", returncode=0,
    ))
    verdict, _duration, _returncode = run_all._run("G32", ["guard"])
    assert verdict == "FAIL"
    assert "reason=missing_verdict_line" in capsys.readouterr().out


def test_runner_orders_all_guards_and_passes_required_scope(monkeypatch, capsys):
    monkeypatch.setenv("BC4_DSN", "postgresql://disposable")
    seen = []

    def fake_run(name, command):
        seen.append((name, command))
        return "PASS", 0.01, 0

    monkeypatch.setattr(run_all, "_run", fake_run)
    result = run_all.main([
        "--base-url", "http://127.0.0.1:9182", "--token", "test-token",
    ])
    assert result == 0
    assert [name for name, _command in seen] == ["G18b", "G24", "G24b", "G32", "G51"]
    g24 = dict(seen)["G24"]
    assert g24[-2:] == ["--pid", "43e81a34a073"]
    g51 = dict(seen)["G51"]
    assert "--base-url" in g51 and "--capture" in g51
    assert "GUARDS VERDICT=PASS passed=5/5" in capsys.readouterr().out


def test_runner_global_fail_if_one_guard_fails(monkeypatch, capsys):
    monkeypatch.setenv("BC4_DSN", "postgresql://disposable")
    monkeypatch.setattr(
        run_all, "_run",
        lambda name, command: ("FAIL", 0.01, 1) if name == "G24" else ("PASS", 0.01, 0),
    )
    assert run_all.main([
        "--base-url", "http://127.0.0.1:9182", "--token", "test-token",
    ]) == 1
    assert "GUARDS VERDICT=FAIL passed=4/5" in capsys.readouterr().out
