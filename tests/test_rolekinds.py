"""The kinds of work a title names, for Today's Roles checkboxes."""

from jobwatch.rolekinds import labels, role_kinds


def test_a_title_names_every_kind_it_matches_and_other_when_none():
    assert role_kinds("Lead Cloud Security Engineer - Threat Hunting") == ["security", "software"]
    assert role_kinds("Senior Machine Learning Engineer") == ["ai", "software"]
    assert role_kinds("Security Automation Engineer, AI Agents") == ["security", "automation", "ai", "software"]
    assert role_kinds("Field Engineer, Solutions") == ["forward", "software"]
    assert role_kinds("Senior Software Engineer, Payments") == ["software"]
    assert role_kinds("Director, Incident Handling") == ["security"]
    assert role_kinds("Head of Product") == ["other"] and role_kinds("") == ["other"]


def test_short_words_match_whole_words_only():
    assert role_kinds("Maintenance Planner") == ["other"]  # "ai" inside a word isn't AI
    assert role_kinds("Social Media Lead") == ["other"]  # nor "soc" inside "social"
    assert "ai" in role_kinds("Gen AI Platform Lead") and "ai" in role_kinds("ML Infrastructure Engineer")


def test_the_page_gets_every_kind_with_other_last():
    keys = [k for k, _ in labels()]
    assert keys == ["security", "automation", "ai", "forward", "software", "other"]
