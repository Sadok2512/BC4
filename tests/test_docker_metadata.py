from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_backend_version_and_oci_build_metadata_are_not_stale():
    pyproject = (ROOT / "pyproject.toml").read_text()
    main = (ROOT / "app/main.py").read_text()
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert 'version = "0.120.1"' in pyproject
    assert main.count('"version": "0.120.1"') == 1
    assert 'version="0.120.1"' in main
    assert "ARG VCS_REF\n" in dockerfile
    assert "ARG APP_VERSION\n" in dockerfile
    assert "VCS_REF=unknown" not in dockerfile
    assert "APP_VERSION=0." not in dockerfile
