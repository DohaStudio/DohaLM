import json
import logging

from src.data.safety import SafeDatasetInspector, guard_safe_output


def _require(condition: bool) -> None:
    if not condition:
        raise AssertionError("SAFE_INSPECTOR_TEST_FAILED")


def _synthetic_record() -> dict:
    return {
        "short_text": "SYNTHETIC_ALPHA_TEXT",
        "long_text": "SYNTHETIC_LONG_VALUE_" * 400,
        "multiline": "SYNTHETIC_LINE_ONE\nSYNTHETIC_LINE_TWO",
        "languages": ["합성한글값", "SYNTHETIC_ENGLISH_VALUE", "1234567890", "!@#$%^&*()"],
        "shapes": {
            "email": "synthetic.user@synthetic.invalid",
            "phone": "000-0000-0000",
            "address": "합성시 가상구 테스트로 0",
            "json_text": '{"synthetic": "value"}',
        },
        "tuple_value": ("SYNTHETIC_TUPLE_VALUE", None),
        "set_value": {"SYNTHETIC_SET_VALUE"},
        "bytes_value": b"SYNTHETIC_BYTES_VALUE",
        "null_value": None,
        "empty_value": "",
        "whitespace_value": " \t\n",
    }


def _serialized(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _all_synthetic_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values():
            result.extend(_all_synthetic_strings(item))
        return result
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            result.extend(_all_synthetic_strings(item))
        return result
    return []


def test_string_is_represented_without_value():
    source = "SYNTHETIC_STRING_VALUE"
    result = SafeDatasetInspector().inspect(source, path="$.field")
    serialized = _serialized(result)
    _require(result["status"] == "ok")
    _require(result["result"]["length"] == len(source))
    _require(source not in serialized)
    _require(result["result"]["sha256"] is None)


def test_string_hash_is_full_sha256_without_plaintext():
    source = "SYNTHETIC_HASH_SOURCE"
    result = SafeDatasetInspector(hash_strings=True).inspect(source)
    digest = result["result"]["sha256"]
    _require(isinstance(digest, str) and len(digest) == 71)
    _require(source not in _serialized(result))


def test_nested_synthetic_fixture_contains_no_source_values():
    source = _synthetic_record()
    result = SafeDatasetInspector(hash_strings=True).inspect(source)
    serialized = _serialized(result)
    _require(result["status"] == "ok")
    for value in _all_synthetic_strings(source):
        _require(not value or value not in serialized)


def test_nested_container_types_are_metadata_only():
    result = SafeDatasetInspector().inspect(_synthetic_record())
    root = result["result"]
    _require(root["type"] == "object")
    _require(root["fields"]["languages"]["type"] == "array")
    _require(root["fields"]["bytes_value"]["type"] == "bytes")
    _require(root["fields"]["null_value"]["type"] == "null")


def test_empty_and_whitespace_flags_are_safe():
    inspector = SafeDatasetInspector()
    empty = inspector.inspect("")["result"]
    whitespace = inspector.inspect(" \t\n")["result"]
    _require(empty["empty"] is True and empty["length"] == 0)
    _require(whitespace["whitespace_only"] is True and whitespace["length"] == 3)


def test_long_string_emits_only_metadata(capsys, caplog):
    source = "SYNTHETIC_LONG_NONCANONICAL_CATEGORY_" * 1000
    with caplog.at_level(logging.DEBUG):
        result = SafeDatasetInspector().inspect(source, path="$.data_category.main")
    captured = capsys.readouterr()
    _require(result["status"] == "ok")
    _require(result["result"]["length"] == len(source))
    _require(captured.out == "" and captured.err == "" and caplog.text == "")
    _require(source not in _serialized(result))


def test_noncanonical_category_value_is_never_emitted(capsys, caplog):
    source = "SYNTHETIC_CATEGORY_PROSE_" * 80
    with caplog.at_level(logging.DEBUG):
        result = SafeDatasetInspector().inspect_category(
            source,
            path="$.data_category.main",
            canonical_values=frozenset({"SYNTHETIC_CANONICAL_A", "SYNTHETIC_CANONICAL_B"}),
        )
    captured = capsys.readouterr()
    _require(result["status"] == "ok")
    _require(result["canonical_match"] is False)
    _require(result["length"] == len(source))
    _require(source not in _serialized(result))
    _require(captured.out == "" and captured.err == "" and caplog.text == "")


def test_canonical_category_reports_only_match_boolean():
    source = "SYNTHETIC_CANONICAL_A"
    result = SafeDatasetInspector().inspect_category(
        source,
        path="$.category",
        canonical_values=frozenset({source}),
    )
    _require(result["canonical_match"] is True)
    _require(source not in _serialized(result))


def test_category_type_mismatch_has_fixed_error_without_value():
    result = SafeDatasetInspector().inspect_category(
        {"unsafe": "SYNTHETIC_HIDDEN_VALUE"},
        path="$.category",
        canonical_values=frozenset(),
    )
    _require(result["error_code"] == "UNSUPPORTED_VALUE_TYPE")
    _require("SYNTHETIC_HIDDEN_VALUE" not in _serialized(result))


def test_guard_blocks_exact_raw_value_injected_into_result():
    source = "SYNTHETIC_RAW_VALUE_FOR_GUARD"
    blocked = guard_safe_output({"status": "ok", "unsafe": source}, source)
    _require(blocked is not None)
    _require(blocked["error_code"] == "RAW_VALUE_LEAK_DETECTED")
    _require(source not in _serialized(blocked))


def test_guard_blocks_long_source_substring():
    source = "SYNTHETIC_SUBSTRING_SOURCE_VALUE"
    blocked = guard_safe_output({"status": "ok", "unsafe": source[4:24]}, source)
    _require(blocked is not None)
    _require(blocked["error_code"] == "RAW_VALUE_LEAK_DETECTED")
    _require(source not in _serialized(blocked))


def test_unsafe_dictionary_key_is_replaced_by_full_digest():
    unsafe_key = "SYNTHETIC KEY CONTAINING PRIVATE VALUE"
    result = SafeDatasetInspector().inspect({unsafe_key: "SYNTHETIC_FIELD_VALUE"})
    serialized = _serialized(result)
    _require(result["status"] == "ok")
    _require(unsafe_key not in serialized)
    _require("SYNTHETIC_FIELD_VALUE" not in serialized)


def test_exception_attributes_and_message_are_never_emitted():
    source = RuntimeError("SYNTHETIC_EXCEPTION_SECRET")
    source.synthetic_attribute = "SYNTHETIC_EXCEPTION_ATTRIBUTE"
    result = SafeDatasetInspector().inspect(source)
    serialized = _serialized(result)
    _require(result["status"] == "ok")
    _require("SYNTHETIC_EXCEPTION_SECRET" not in serialized)
    _require("SYNTHETIC_EXCEPTION_ATTRIBUTE" not in serialized)


def test_malformed_custom_object_fails_closed_without_exception_text(capsys):
    class SyntheticMalformedObject:
        __slots__ = ()

    result = SafeDatasetInspector().inspect(SyntheticMalformedObject())
    captured = capsys.readouterr()
    serialized = _serialized(result)
    _require(result["status"] == "blocked")
    _require(result["error_code"] == "UNSUPPORTED_VALUE_TYPE")
    _require("SYNTHETIC_INTERNAL_EXCEPTION_VALUE" not in serialized)
    _require(captured.out == "" and captured.err == "")


def test_string_aggregate_contains_counts_not_values():
    source = ["SYNTHETIC_ONE", "SYNTHETIC_TWO_LONGER", "", "  "]
    result = SafeDatasetInspector().aggregate_strings(source, path="$.values")
    serialized = _serialized(result)
    _require(result["status"] == "ok" and result["count"] == 4)
    _require(result["empty_count"] == 1 and result["whitespace_only_count"] == 1)
    for value in source:
        _require(not value or value not in serialized)
