from app.services.llm.json_repair import (
    escape_control_chars_in_json_strings,
    extract_first_json,
    parse_repaired_json,
)


def test_control_characters_inside_strings_are_escaped_only_inside_strings():
    assert escape_control_chars_in_json_strings('{"a":"x\ny\tz"}') == '{"a":"x\\ny\\tz"}'
    assert escape_control_chars_in_json_strings('{\n"a":1\n}') == '{\n"a":1\n}'


def test_extracts_first_balanced_value_and_ignores_braces_in_strings():
    assert extract_first_json('prefix {"a":"}"} suffix') == '{"a":"}"}'
    assert extract_first_json('{"a":1}{"b":2}') == '{"a":1}'
    assert extract_first_json('junk [1,2] tail') == '[1,2]'
    assert extract_first_json('{"a":[') is None


def test_parser_recovers_fences_prose_and_raw_newlines():
    assert parse_repaired_json('```json\n{"a":1}\n```') == {"a": 1}
    assert parse_repaired_json('Here: {"a":1} thanks') == {"a": 1}
    assert parse_repaired_json('{"a":"x\ny"}') == {"a": "x\ny"}
    assert parse_repaired_json('garbage') is None


def test_list_mode_unwraps_first_list_value():
    assert parse_repaired_json('{"questions":[1,2]}', expect="list") == [1, 2]
