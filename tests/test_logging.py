import logging

from src.runtime.log_setup import configure_logging


def test_reconfiguration_does_not_duplicate_handlers():
    logger = configure_logging(logger_name="dohalm.test.duplicate")
    logger = configure_logging(logger_name="dohalm.test.duplicate")
    assert len(logger.handlers) == 1


def test_utf8_korean_file_logging_and_secret_masking(tmp_path):
    destination = tmp_path / "nested" / "테스트.log"
    logger = configure_logging(
        logger_name="dohalm.test.utf8",
        log_file=destination,
        experiment_id="phase0",
    )
    logger.info("한글 로그 api_key=very-secret Bearer token-value")
    for handler in logger.handlers:
        handler.flush()
    content = destination.read_text(encoding="utf-8")
    assert "한글 로그" in content
    assert "experiment=phase0" in content
    assert "very-secret" not in content
    assert "token-value" not in content
    assert "api_key=***" in content


def test_no_file_is_created_without_file_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    configure_logging(logger_name="dohalm.test.console")
    assert list(tmp_path.iterdir()) == []
