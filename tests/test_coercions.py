"""
Tests for ehrzipper/coercions.py — port of zippering-coercions.test.ts.

All test cases mirror the TypeScript originals exactly. Test names are
transliterated from the describe/it structure.
"""

from __future__ import annotations

import pytest

from ehrzipper.coercions import UnsafeCoercion, normalize

# ---------------------------------------------------------------------------
# normalize — identity
# ---------------------------------------------------------------------------


class TestNormalizeIdentity:
    def test_returns_same_value_text(self) -> None:
        assert normalize("foo", "text", "text") == "foo"

    def test_returns_same_value_integer(self) -> None:
        assert normalize(42, "integer", "integer") == 42

    def test_returns_same_value_boolean(self) -> None:
        assert normalize(True, "boolean", "boolean") is True

    def test_returns_same_value_jsonb(self) -> None:
        obj = {"a": 1}
        assert normalize(obj, "jsonb", "jsonb") is obj


# ---------------------------------------------------------------------------
# normalize — registered coercions (happy paths)
# ---------------------------------------------------------------------------


class TestNormalizeRegisteredCoercions:
    def test_integer_to_text(self) -> None:
        assert normalize(123, "integer", "text") == "123"

    def test_numeric_to_text(self) -> None:
        assert normalize(3.14, "numeric", "text") == "3.14"

    def test_text_to_integer_valid(self) -> None:
        assert normalize("42", "text", "integer") == 42

    def test_integer_to_timestamp_epoch_zero(self) -> None:
        result = normalize(0, "integer", "timestamp")
        assert result == "1970-01-01T00:00:00.000Z"

    def test_timestamp_to_integer_epoch_zero(self) -> None:
        result = normalize("1970-01-01T00:00:00.000Z", "timestamp", "integer")
        assert result == 0

    def test_text_to_timestamp_parses_date(self) -> None:
        result = normalize("2024-01-15", "text", "timestamp")
        assert isinstance(result, str)
        # result should be parseable as a year-2024 date
        assert "2024" in result

    def test_text_to_string_array(self) -> None:
        assert normalize("hello", "text", "string[]") == ["hello"]

    def test_string_array_to_jsonb_passthrough(self) -> None:
        arr = ["a", "b", "c"]
        assert normalize(arr, "string[]", "jsonb") is arr

    def test_text_to_jsonb_passthrough(self) -> None:
        assert normalize("raw text", "text", "jsonb") == "raw text"

    def test_integer_to_timestamp_roundtrip(self) -> None:
        """epoch_ms → ISO string → epoch_ms should be stable."""
        epoch_ms = 1_716_681_600_000
        iso = normalize(epoch_ms, "integer", "timestamp")
        assert isinstance(iso, str)
        recovered = normalize(iso, "timestamp", "integer")
        assert abs(int(recovered) - epoch_ms) < 1000  # within 1 s


# ---------------------------------------------------------------------------
# normalize — unsafe coercions
# ---------------------------------------------------------------------------


class TestNormalizeUnsafeCoercions:
    def test_text_to_integer_non_numeric_raises(self) -> None:
        with pytest.raises(UnsafeCoercion):
            normalize("not-a-number", "text", "integer")

    def test_text_to_integer_error_contains_value(self) -> None:
        with pytest.raises(UnsafeCoercion) as exc_info:
            normalize("abc", "text", "integer")
        assert "abc" in str(exc_info.value)
        assert exc_info.value.name == "UnsafeCoercion"

    def test_text_to_timestamp_invalid_string_raises(self) -> None:
        with pytest.raises(UnsafeCoercion):
            normalize("not-a-date", "text", "timestamp")

    def test_unregistered_boolean_to_string_array_raises(self) -> None:
        with pytest.raises(UnsafeCoercion):
            normalize(True, "boolean", "string[]")

    def test_unregistered_jsonb_to_integer_raises(self) -> None:
        with pytest.raises(UnsafeCoercion):
            normalize({}, "jsonb", "integer")

    def test_unsafe_coercion_attributes(self) -> None:
        """UnsafeCoercion carries from_type, to_type, and value attributes."""
        try:
            normalize("xyz", "text", "integer")
            pytest.fail("Expected UnsafeCoercion")
        except UnsafeCoercion as e:
            assert e.from_type == "text"
            assert e.to_type == "integer"
            assert e.value == "xyz"

    def test_text_to_integer_non_string_raises(self) -> None:
        """text→integer coercer requires a str value; non-str should raise."""
        with pytest.raises(UnsafeCoercion):
            normalize(3.14, "text", "integer")
