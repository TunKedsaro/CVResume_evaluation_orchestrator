# tests/test_role_context_assembler.py
from __future__ import annotations

from functions.orchestrator.role_context_assembler import RoleContextAssembler


def test_build_returns_none_when_role_core_not_dict() -> None:
    assert RoleContextAssembler.build(None) is None  # type: ignore[arg-type]
    assert RoleContextAssembler.build("x") is None  # type: ignore[arg-type]
    assert RoleContextAssembler.build([]) is None  # type: ignore[arg-type]


def test_build_returns_none_when_no_meaningful_fields_exist() -> None:
    # empty dict -> no title/desc/skills/responsibilities
    assert RoleContextAssembler.build({}) is None

    # role object exists but empty
    assert RoleContextAssembler.build({"role": {}}) is None


def test_build_extracts_title_from_role_object_and_formats_role_line() -> None:
    role_core = {"role": {"role_title": "AI Engineer"}}
    ctx = RoleContextAssembler.build(role_core)
    assert ctx is not None
    assert ctx.splitlines()[0] == "Role: AI Engineer"


def test_build_extracts_title_from_top_level_fallbacks() -> None:
    role_core = {"role_title": "AI Engineer"}
    ctx = RoleContextAssembler.build(role_core)
    assert ctx is not None
    assert "Role: AI Engineer" in ctx


def test_build_includes_description_when_present() -> None:
    role_core = {"role": {"role_title": "AI Engineer", "role_description": "Builds ML systems."}}
    ctx = RoleContextAssembler.build(role_core)
    assert ctx is not None
    assert "Description: Builds ML systems." in ctx


def test_build_formats_required_skills_with_and_without_proficiency() -> None:
    role_core = {
        "role": {"role_title": "AI Engineer"},
        "required_skills": [
            {"skill_name": "Python", "role_required_skills_proficiency_lv": "Advanced"},
            {"skill_name": "FastAPI"},
            {"name": "BigQuery", "proficiency": "Intermediate"},
            {"skillName": "Docker"},  # camelCase field name
        ],
    }

    ctx = RoleContextAssembler.build(role_core)
    assert ctx is not None

    # Section header exists
    assert "Required skills:" in ctx

    # Skill lines exist
    assert "- Python (Advanced)" in ctx
    assert "- FastAPI" in ctx
    assert "- BigQuery (Intermediate)" in ctx
    assert "- Docker" in ctx


def test_extract_responsibilities_supports_list_str_list_dict_and_string_and_dedupes() -> None:
    role_core = {
        "role": {
            "role_title": "AI Engineer",
            "role_responsibilities": [
                "Build ML services",
                "Build ML services",  # duplicate
                {"responsibility": "Maintain pipelines"},
                {"text": "Improve reliability"},
            ],
        },
        "responsibilities": "Improve reliability",  # duplicate but different location
    }

    ctx = RoleContextAssembler.build(role_core)
    assert ctx is not None

    # Header exists
    assert "Key responsibilities:" in ctx

    # Bullets exist (deduped)
    assert "- Build ML services" in ctx
    assert "- Maintain pipelines" in ctx
    assert "- Improve reliability" in ctx

    # Ensure "Improve reliability" is not duplicated
    assert ctx.count("Improve reliability") == 1


def test_build_handles_role_obj_key_variants() -> None:
    # title and description exist at top-level in alternative keys
    role_core = {
        "roleTitle": "AI Engineer",
        "roleDescription": "Works on LLM systems.",
        "required_skills": [{"skill_name": "Python"}],
    }

    ctx = RoleContextAssembler.build(role_core)
    assert ctx is not None
    assert "Role: AI Engineer" in ctx
    assert "Description: Works on LLM systems." in ctx
    assert "- Python" in ctx
