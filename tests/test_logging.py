"""Worker root logging must never interpolate untrusted external messages."""

import json
import logging

import pytest

from crm_workflow.worker import SafeJsonFormatter


def record(logger: str, message: str, args=(), **extra):
    entry = logging.LogRecord(
        name=logger,
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=args,
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(entry, key, value)
    return entry


@pytest.mark.parametrize("logger", ["httpx", "temporalio.service", "crm_workflow.worker"])
def test_untrusted_log_messages_and_extra_fields_are_redacted(logger):
    marker = "synthetic-private-token-marker"
    event = record(logger, "upstream authorization was %s", (marker,), case_id=marker)
    output = SafeJsonFormatter().format(event)
    decoded = json.loads(output)
    assert marker not in output
    assert "authorization" not in output
    assert decoded["event"] == "untrusted_log_redacted"
    assert decoded["logger"] == "external_or_unrecognized"
    assert "case_id" not in decoded


def test_known_worker_activity_preserves_allowlisted_diagnostics():
    observed = record(
        "crm_workflow.worker",
        "activity_started",
        case_id="a1c8bdb0-17af-45e0-8800-507ac8e3b763",
        operation="execute_crm",
        attempt=2,
    )
    decoded = json.loads(SafeJsonFormatter().format(observed))
    assert decoded["event"] == "activity_started"
    assert decoded["logger"] == "crm_workflow.worker"
    assert decoded["case_id"] == "a1c8bdb0-17af-45e0-8800-507ac8e3b763"
    assert decoded["operation"] == "execute_crm"
    assert decoded["attempt"] == 2


def test_external_logger_cannot_forge_an_application_event():
    marker = "synthetic-private-extra"
    decoded = json.loads(
        SafeJsonFormatter().format(record("temporalio.client", "activity_started", (), outbox_id=marker))
    )
    assert decoded["event"] == "untrusted_log_redacted"
    assert "outbox_id" not in decoded
