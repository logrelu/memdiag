import pytest

from memdiag.prompt import load_prompt, parse_prompt


def test_shipped_prompt_loads_and_renders():
    p = load_prompt("extract_facts")
    assert (p.id, p.version) == ("extract_facts", 2)
    text = p.render(message="We just moved to Denver.", known_people="- daughter: Maya")
    assert "- daughter: Maya" in text
    assert text.endswith("We just moved to Denver.")
    assert '{"facts": []}' in text  # JSON braces survive templating


def test_missing_field_raises():
    with pytest.raises(KeyError):
        load_prompt("extract_facts").render()


def test_bad_headers_are_rejected():
    with pytest.raises(ValueError, match="header"):
        parse_prompt("no header here")
    with pytest.raises(ValueError, match="version"):
        parse_prompt("id: x\n---\nbody")
    assert parse_prompt("id: x\nversion: 3\n---\nhi $a").render(a="there") == "hi there"
