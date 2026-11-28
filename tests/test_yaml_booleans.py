"""YAML 1.1 (PyYAML, which reads the watchlist) takes an unquoted No, Yes, on or off for a boolean, and NO (Norway)
for false. The settings page's own save used to write `hispanic: No` bare (ruamel is YAML 1.2), and the next load
refused its own file with "applicant.hispanic is text, got False"."""
import json

import pytest
import yaml

from jobwatch import config
from jobwatch.web import App

from .conftest import TOKEN, request


def _write(path, extra: str):
    path.write_text(path.read_text() + extra)


def test_applicant_text_fields_accept_a_boolean_for_the_word_it_was(watchlist):
    _write(watchlist, "applicant:\n  hispanic: No\n  veteran: Yes\n  gender: off\n  race: on\n  disability: no\n"
                      "  country: NO\n  state: ON\n  relocate: yes\n  notice_period:\n")
    a = config.load(watchlist).applicant
    assert (a.hispanic, a.veteran, a.gender, a.race, a.disability) == ("No", "Yes", "No", "Yes", "No")
    assert (a.country, a.state, a.relocate, a.notice_period) == ("NO", "ON", "yes", "")  # NO is Norway


def test_applicant_wrong_type_names_the_field_and_the_fix(watchlist):
    _write(watchlist, "applicant:\n  email: [a, b]\n")
    with pytest.raises(config.ConfigError, match=r"applicant\.email is text, got \['a', 'b'\]; write it as text"):
        config.load(watchlist)


@pytest.mark.parametrize("text, says", [
    ("goals:\n  about: No\n", 'goals.about is text in your own words, got False (YAML reads an unquoted yes, no, on '
                              'or off as true or false: write it in quotes, like "No")'),
    ("companies:\n  - {source: greenhouse, board: acme, name: On}\n", "companies entry name is text, got True"),
    ("employer: [On]\n", "employer holds text, got True"),
    ("employer: No\n", "employer holds text, got False"),
    ("connections_skip: [Jane Doe, No]\n", "connections_skip holds text, got False"),
    ("focus: [security, off]\n", "focus holds text, got False"),
    ("learning:\n  near: No\n", "learning.near is a city, got False"),
    ("filters:\n  exclude_titles: [off]\n", 'filters.exclude_titles: False isn\'t a valid pattern'),
    ("filters:\n  exclude_companies: [Initech, On]\n", "filters.exclude_companies holds text, got True"),
    ("filters:\n  home_state: No\n", "filters.home_state is text, got False"),
])
def test_a_misread_word_is_refused_by_name_with_the_fix(tmp_path, text, says):
    path = tmp_path / "jobwatch.yaml"
    body = "companies:\n  - greenhouse:acme\n"
    path.write_text(text if text.startswith("companies") else body + text)
    with pytest.raises(config.ConfigError) as e:
        config.load(path)
    assert says in str(e.value) and ("write it in quotes" in str(e.value) or "isn't a valid" in str(e.value))


def test_country_codes_in_filters_read_as_codes(watchlist):
    watchlist.write_text(watchlist.read_text().replace("locations: [remote, Denver]",
                                                       "locations: [remote, NO, Denver]\n  remote_country: NO"))
    cfg = config.load(watchlist)
    assert cfg.filters.locations == ["remote", "NO", "Denver"] and cfg.filters.remote_country == "NO"


def test_save_writes_a_misread_word_quoted_and_the_file_loads_back(watchlist):
    cfg = config.save(watchlist, {"applicant": {"hispanic": "No", "veteran": "YES", "gender": "off",
                                                "country": "NO", "relocate": "no", "notice_period": "2",
                                                "city": "Boulder"},
                                  "employer": ["On"]})
    text = watchlist.read_text()
    assert 'hispanic: "No"' in text and 'veteran: "YES"' in text and 'country: "NO"' in text
    assert "city: Boulder" in text  # plain text stays bare
    assert (cfg.applicant.hispanic, cfg.applicant.country, cfg.applicant.relocate) == ("No", "NO", "no")
    assert cfg.employer == ["On"]
    assert yaml.safe_load(text)["applicant"]["hispanic"] == "No"  # PyYAML reads it as text now


def test_save_quotes_a_bare_word_the_file_already_carried(watchlist):
    _write(watchlist, "applicant:\n  hispanic: No  # kept\n  city: Boulder\n")
    cfg = config.save(watchlist, {"applicant": {"hispanic": "No", "city": "Boulder", "email": "jordan@example.com"}})
    text = watchlist.read_text()
    assert 'hispanic: "No"' in text and "# kept" in text and cfg.applicant.hispanic == "No"


def test_the_settings_page_shows_a_bare_no_as_text_and_its_save_round_trips(server, watchlist):
    _write(watchlist, "applicant:\n  hispanic: No\n  veteran: Yes\n  relocate: no\n  first_name: Jordan\n")
    headers = {"X-Jobwatch-Token": TOKEN}
    got = json.loads(request(server, "GET", "/api/settings", headers=headers)[1])
    shown = got["applicant"]
    assert (shown["hispanic"], shown["veteran"], shown["relocate"]) == ("No", "Yes", "no")
    # the page sends back what it was shown (merged with what it edits): Save no longer refuses its own file
    body = {"applicant": {**shown, "first_name": "Jordan"}, "file_version": got["file_version"]}
    assert request(server, "POST", "/api/settings", body, headers=headers)[0] == 200
    text = watchlist.read_text()
    assert 'hispanic: "No"' in text and 'veteran: "Yes"' in text
    a = config.load(watchlist).applicant
    assert (a.hispanic, a.veteran, a.relocate, a.first_name) == ("No", "Yes", "no", "Jordan")


def test_the_page_posting_false_as_text_still_saves(watchlist):
    """What the old page sent for a bare No: the text "false" (an input shown the boolean)."""
    app = App(watchlist)
    app.post_settings({"applicant": {"hispanic": "false"}})
    assert config.load(watchlist).applicant.hispanic == "false"
    assert 'hispanic: "false"' in watchlist.read_text() or "hispanic: 'false'" in watchlist.read_text()
