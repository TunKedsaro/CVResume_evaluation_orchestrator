# tests/test_json_naming_converter.py
from __future__ import annotations

from functions.utils.json_naming_converter import snake_to_camel, convert_keys_snake_to_camel


def test_snake_to_camel_basic() -> None:
    assert snake_to_camel("final_resume_score") == "finalResumeScore"
    assert snake_to_camel("section_detail") == "sectionDetail"
    assert snake_to_camel("x") == "x"  # unchanged when no underscore


def test_snake_to_camel_preserves_leading_and_trailing_underscores() -> None:
    assert snake_to_camel("_hello_world") == "_helloWorld"
    assert snake_to_camel("hello_world_") == "helloWorld_"
    assert snake_to_camel("__hello_world__") == "__helloWorld__"
    assert snake_to_camel("___") == "___"  # only underscores


def test_convert_keys_snake_to_camel_converts_nested_dict_and_list_keys() -> None:
    inp = {
        "final_resume_score": 34.0,
        "section_contribution": {
            "Profile": {"section_total": 20.0, "section_weight": 0.1},
        },
        "section_detail": [
            {"total_score": 10, "score_detail": {"content_quality": 10}},
        ],
    }

    out = convert_keys_snake_to_camel(inp)

    assert "finalResumeScore" in out
    assert out["finalResumeScore"] == 34.0

    assert "sectionContribution" in out
    assert out["sectionContribution"]["Profile"]["sectionTotal"] == 20.0
    assert out["sectionContribution"]["Profile"]["sectionWeight"] == 0.1

    assert "sectionDetail" in out
    assert out["sectionDetail"][0]["totalScore"] == 10
    assert out["sectionDetail"][0]["scoreDetail"]["contentQuality"] == 10


def test_convert_keys_snake_to_camel_leaves_primitives_intact() -> None:
    assert convert_keys_snake_to_camel("x") == "x"
    assert convert_keys_snake_to_camel(123) == 123
    assert convert_keys_snake_to_camel(None) is None
    assert convert_keys_snake_to_camel(True) is True


def test_convert_keys_snake_to_camel_preserve_container_keys_preserves_child_keys() -> None:
    """
    If a key is listed in preserve_container_keys:
      - the container key itself is converted
      - inner dict keys are NOT converted
    """
    inp = {
        "user_or_llm_comments": {  # container key should become userOrLlmComments
            "profile_summary": "keep_this_key",
            "experience_1": "keep_this_key_too",
        },
        "normal_block": {
            "inner_key_one": 1,
        },
    }

    out = convert_keys_snake_to_camel(inp, preserve_container_keys=["user_or_llm_comments"])

    # container key converted
    assert "userOrLlmComments" in out

    # inner keys preserved exactly (still snake_case)
    preserved = out["userOrLlmComments"]
    assert "profile_summary" in preserved
    assert "experience_1" in preserved
    assert preserved["profile_summary"] == "keep_this_key"

    # other blocks still convert normally
    assert out["normalBlock"]["innerKeyOne"] == 1


def test_convert_keys_snake_to_camel_preserve_container_keys_accepts_camel_name_too() -> None:
    """
    Code supports specifying preserve keys in snake_case OR camelCase.
    """
    inp = {
        "user_or_llm_comments": {"profile_summary": "x"},
    }

    out = convert_keys_snake_to_camel(inp, preserve_container_keys=["userOrLlmComments"])

    assert "userOrLlmComments" in out
    assert "profile_summary" in out["userOrLlmComments"]  # preserved
