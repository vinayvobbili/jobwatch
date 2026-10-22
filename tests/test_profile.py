"""A LinkedIn experience page's text, parsed into roles: the text comes from the person, nothing is fetched."""

import json

import pytest

from jobwatch import cli, profile

mcp = pytest.importorskip("jobwatch.mcp_server")

# The shape a browser's page text has for /details/experience/ (synthetic person): a company with two roles under
# one header, a single role with a "Company · Full-time" line, wrapped bullets, then the sidebar and footer.
PAGE = """Title: Pat Example | LinkedIn
URL: https://www.linkedin.com/in/example/details/experience/
Source element: <main>
---
Experience

Acme Security

Full-time · 3 yrs 3 mos

Austin, Texas, United States

VP Solutions

Mar 2024 - Present · 2 yrs 8 mos

Hybrid

Director of Solution Engineering

Aug 2023 - Mar 2024 · 8 mos

Senior Product Manager - Endpoint

Bigco · Full-time

Jan 2020 - Aug 2023 · 3 yrs 8 mos

Seattle, Washington, United States

- Owned the isolation feature end to end.
- Worked with customers on technical requirements to provide
solutions for their SOC.

Engineer

Army

2003 - 2006

Israel

Built the system that ran the base.

More profiles for you

Sam Other

· 3rd

About

Accessibility
"""


def test_roles_under_a_company_header_take_its_name():
    found = profile.roles(PAGE)
    assert [(r.title, r.company) for r in found] == [
        ("VP Solutions", "Acme Security"),
        ("Director of Solution Engineering", "Acme Security"),
        ("Senior Product Manager - Endpoint", "Bigco"),
        ("Engineer", "Army"),
    ]


def test_dates_location_workplace_and_wrapped_bullets():
    vp, director, pm, army = profile.roles(PAGE)
    assert (vp.start, vp.end, vp.duration, vp.workplace) == ("Mar 2024", "Present", "2 yrs 8 mos", "Hybrid")
    assert director.bullets == [] and director.location == ""
    assert pm.location == "Seattle, Washington, United States"
    assert pm.bullets == ["Owned the isolation feature end to end.",
                          "Worked with customers on technical requirements to provide solutions for their SOC."]
    assert (army.start, army.end, army.duration) == ("2003", "2006", "")
    assert army.location == "Israel"  # no comma, still a location
    assert army.bullets == ["Built the system that ran the base."]  # a sentence is description, not location


def test_sidebar_and_footer_are_dropped():
    assert all("Sam Other" not in r.bullets and "Accessibility" not in " ".join(r.bullets)
               for r in profile.roles(PAGE))


def test_html_escapes_and_nests_bullets():
    out = profile.render(profile.roles(PAGE.replace("end to end", "A & B")), "html")
    assert out.startswith("<ul>") and "<li><b>Bigco:</b> Senior Product Manager - Endpoint" in out
    assert "A &amp; B" in out and "<ul><li>" in out


def test_cli_prints_the_roles_in_each_format(tmp_path, capsys):
    page = tmp_path / "p.txt"
    page.write_text(PAGE)
    cli.main(["profile", str(page)])
    assert "VP Solutions, Acme Security (Mar 2024 – Present, 2 yrs 8 mos)" in capsys.readouterr().out
    cli.main(["profile", str(page), "--format", "json"])
    assert json.loads(capsys.readouterr().out)[3]["location"] == "Israel"


def test_cli_without_roles_exits_with_a_message(tmp_path):
    page = tmp_path / "p.txt"
    page.write_text("Experience\nNothing here\n")
    with pytest.raises(SystemExit, match="no roles found"):
        cli.main(["profile", str(page)])


def test_mcp_tool_returns_the_roles_and_rejects_a_page_without_any():
    found = mcp.read_profile(PAGE)
    assert [r["company"] for r in found] == ["Acme Security", "Acme Security", "Bigco", "Army"]
    with pytest.raises(mcp.ToolError, match="no roles found"):
        mcp.read_profile("https://www.linkedin.com/in/example/")
