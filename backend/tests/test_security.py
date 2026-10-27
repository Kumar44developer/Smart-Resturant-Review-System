"""Security primitives: password hashing, JWT integrity, sanitization, rate limiting."""
from __future__ import annotations

import pytest

from app import security
from app.services import guards


def test_password_hash_roundtrip_and_salth():
    h = security.hash_password("correct horse battery")
    assert h != "correct horse battery"
    assert security.verify_password("correct horse battery", h)
    assert not security.verify_password("wrong password here", h)
    # distinct hashes for the same password (random salt)
    assert security.hash_password("same secret pw") != security.hash_password("same secret pw")


def test_verify_password_rejects_malformed():
    assert security.verify_password("x", "not-a-valid-hash") is False


def test_token_roundtrip_and_tamper_detection():
    tok = security.create_token(42, "a@b.com")
    payload = security.decode_token(tok)
    assert payload and payload["sub"] == "42"
    # flipping a char must not decode
    bad = tok[:-2] + ("ab" if not tok.endswith("ab") else "cd")
    assert security.decode_token(bad) is None
    assert security.decode_token("garbage.token.value") is None


def test_sanitize_strips_tags_and_controls():
    out = guards.sanitize_text("<script>alert(1)</script> hi\x00")
    assert "<script>" not in out and "alert(1)" in out
    assert "\x00" not in out


def test_escape_html():
    assert guards.escape_html('<a href="x">&\'') == "&lt;a href=&quot;x&quot;&gt;&amp;&#x27;"


def test_rate_limit_raises_after_threshold():
    key = "test-bucket-" + str(id(object()))
    from fastapi import HTTPException
    for _ in range(guards.settings.rate_limit_per_min):
        guards.rate_limit(key)
    with pytest.raises(HTTPException) as e:
        guards.rate_limit(key)
    assert e.value.status_code == 429
