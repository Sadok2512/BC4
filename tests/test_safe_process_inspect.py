from scripts.safe_process_inspect import redact_process_line


def test_redacts_sensitive_assignments_options_and_url_credentials() -> None:
    raw = (
        "docker run -e BC4_DSN=postgresql://bc4:db-secret@db/bc4 "
        "-e BC4_JWT_SECRET=jwt-secret -e VENDOR_API_KEY=api-secret "
        "--token bearer-secret"
    )
    safe = redact_process_line(raw)
    assert "db-secret" not in safe
    assert "jwt-secret" not in safe
    assert "api-secret" not in safe
    assert "bearer-secret" not in safe
    assert safe.count("<redacted>") >= 4


def test_keeps_non_sensitive_process_context() -> None:
    safe = redact_process_line("123 1 python -m app.services.import_worker")
    assert safe == "123 1 python -m app.services.import_worker"
