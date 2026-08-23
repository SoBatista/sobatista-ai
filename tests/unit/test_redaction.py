from __future__ import annotations

import logging

from sobai.core.redaction import (
    REDACTED,
    RedactingFilter,
    redact,
    redact_obj,
    register_secret,
)


def test_registered_secret_is_redacted() -> None:
    register_secret("super-secret-value-123")
    assert "super-secret-value-123" not in redact("token=super-secret-value-123 end")
    assert REDACTED in redact("token=super-secret-value-123 end")


def test_short_values_not_registered() -> None:
    register_secret("ab")  # below threshold
    assert redact("value ab here") == "value ab here"


def test_anthropic_key_pattern() -> None:
    out = redact("key sk-ant-abcdEFGH12345678 more")
    assert "abcdEFGH12345678" not in out
    assert "sk-ant-" in out


def test_openai_key_pattern() -> None:
    out = redact("Authorization: Bearer sk-proj-abcdefghij1234567890")
    assert "abcdefghij1234567890" not in out


def test_google_tokens() -> None:
    assert "ya29.SECRETTOKENVALUE" not in redact("ya29.SECRETTOKENVALUE1234")
    assert "1//refreshtokenvaluehere1234" not in redact("1//refreshtokenvaluehere1234")


def test_bearer_header_redacted() -> None:
    out = redact("authorization: bearer abc.def.ghi")
    assert "abc.def.ghi" not in out


def test_redact_obj_recurses() -> None:
    register_secret("nested-secret-value")
    obj = {"a": ["nested-secret-value", 1], "b": {"c": "nested-secret-value"}}
    red = redact_obj(obj)
    assert red["a"][0] == REDACTED
    assert red["b"]["c"] == REDACTED
    assert red["a"][1] == 1


def test_logging_filter_scrubs(caplog) -> None:
    register_secret("logsecret-abcdef")
    logger = logging.getLogger("test.redact")
    logger.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO, logger="test.redact"):
        logger.info("leaking logsecret-abcdef now")
    assert "logsecret-abcdef" not in caplog.text
