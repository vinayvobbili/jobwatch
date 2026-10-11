"""The settings Settings shows that were once fixed in the code: the chat's model, reply length, memory and
instructions; the fit-score model; and how a bad value is refused. Each one is read from the watchlist, has the
old fixed value as its default, and saves through the page's /api/settings."""

from pathlib import Path

import pytest
import yaml

from jobwatch import chat, config
from jobwatch.config import Chat, ConfigError
from jobwatch.web import App

from .conftest import request

PROMPT = "You help Dana Acme look for robotics jobs. Today is {today}.\n\n{context}\n\nKeep it to three lines."


@pytest.fixture
def fake_model(monkeypatch):
    """Stands in for the chat's model: records what it was sent."""
    seen = {}

    def reply(backend, system, messages, model="", max_tokens=0):
        seen.update(backend=backend, system=system, messages=messages, model=model, max_tokens=max_tokens)
        yield "Fine."
    monkeypatch.setattr(chat, "check", lambda backend: None)
    monkeypatch.setattr(chat, "reply", reply)
    return seen


def write(path, **sections):
    raw = yaml.safe_load(path.read_text())
    path.write_text(yaml.safe_dump({**raw, **sections}))


def test_the_defaults_are_the_values_once_fixed_in_the_code(watchlist):
    cfg = config.load(watchlist)
    assert cfg.chat == Chat(backend="local")
    assert (cfg.chat.claude_model, cfg.chat.local_model) == ("claude-sonnet-5-5", "mlx-community/Qwen3.5-9B-MLX-4bit")
    assert (cfg.chat.max_tokens, cfg.chat.max_turns, cfg.chat.prompt) == (1500, 24, "")
    assert cfg.chat.model == "mlx-community/Qwen3.5-9B-MLX-4bit"
    assert (cfg.backend, cfg.score_model, cfg.score_top) == ("local", "", 0)
    assert (cfg.pay.ask_over, cfg.pay.round, cfg.pay.today) == (10, 5000, 15)
    assert (cfg.suggest.half_life, cfg.suggest.limit, cfg.learn_jobs) == (30, 10, 5)
    d = config.defaults()
    assert d["chat"] == {"claude_model": "claude-sonnet-5-5", "local_model": "mlx-community/Qwen3.5-9B-MLX-4bit",
                         "max_tokens": 1500, "max_turns": 24}
    assert d["pay"] == {"levels": False, "region": "", "ask_over": 10, "round": 5000, "today": 15}
    assert d["suggestions"] == {"half_life": 30, "limit": 10} and d["learning"]["jobs"] == 5
    assert d["scoring"] == {"backend": "local", "top": 0} and d["fetch_every"] == "6h"
    assert d["alerts"]["imap"]["senders"] == list(config.ALERT_SENDERS)


def test_the_example_watchlist_shows_the_new_settings_and_loads(tmp_path):
    for key in ("chat:", "claude_model:", "max_tokens:", "max_turns:", "ask_over:", "round:", "half_life:",
                "limit:", "jobs:", "model:"):
        assert key in config.EXAMPLE
    path = tmp_path / "jobwatch.yaml"
    path.write_text(config.EXAMPLE)
    assert config.load(path).chat.backend == "claude"  # left out: the fit scores' backend


def test_the_readme_watchlist_loads(tmp_path):
    readme = (Path(__file__).parent.parent / "README.md").read_text()
    block = readme.split("## The watchlist", 1)[1].split("```yaml\n", 1)[1].split("```", 1)[0]
    path = tmp_path / "jobwatch.yaml"
    path.write_text(block)
    cfg = config.load(path)
    assert (cfg.chat.max_turns, cfg.pay.ask_over, cfg.suggest.half_life, cfg.learn_jobs) == (24, 10, 30, 5)


def test_chat_settings_are_read(watchlist):
    write(watchlist, scoring={"backend": "claude"})
    assert config.load(watchlist).chat.backend == "claude"  # follows the fit scores unless set
    write(watchlist, scoring={"backend": "claude"},
          chat={"backend": "local", "local_model": "mlx-community/Tiny-Test-4bit", "max_tokens": 600,
                "max_turns": 4, "prompt": PROMPT})
    c = config.load(watchlist).chat
    assert (c.backend, c.model, c.max_tokens, c.max_turns, c.prompt) == \
        ("local", "mlx-community/Tiny-Test-4bit", 600, 4, PROMPT)
    write(watchlist, chat={"backend": "claude", "claude_model": "claude-test-model", "prompt": "  "})
    c = config.load(watchlist).chat
    assert (c.model, c.prompt) == ("claude-test-model", "")  # a blank prompt is the default one


@pytest.mark.parametrize("section, says", [
    ({"chat": {"backend": "gpt"}}, r"chat\.backend must be one of claude, local"),
    ({"chat": {"max_tokens": 0}}, r"chat\.max_tokens must be a whole number from 1 to 64000"),
    ({"chat": {"max_tokens": 1e6}}, r"chat\.max_tokens"),
    ({"chat": {"max_turns": "lots"}}, r"chat\.max_turns must be a whole number from 1 to 200"),
    ({"chat": {"max_turns": True}}, r"chat\.max_turns"),
    ({"chat": {"temperature": 0.2}}, "unknown chat setting"),
    ({"chat": "fast"}, "chat looks like"),
    ({"chat": {"prompt": "Help with jobs. {context}"}}, r"chat\.prompt must keep \{today\}"),
    ({"chat": {"prompt": "{today} {context} for {name}"}}, r"unknown placeholder\(s\) \{name\}"),
    ({"chat": {"prompt": "{today} {context} {"}}, r"chat\.prompt.*literal brace"),
    ({"chat": {"prompt": ["a list"]}}, r"chat\.prompt is the assistant's instructions"),
    ({"scoring": {"backend": "gpt"}}, r"scoring\.backend must be one of claude, local"),
    ({"scoring": {"top": -1}}, r"scoring\.top must be a whole number"),
    ({"learning": {"jobs": "some"}}, r"learning\.jobs"),
])
def test_a_bad_setting_is_refused_and_the_file_left_as_it_was(watchlist, section, says):
    before = watchlist.read_bytes()
    with pytest.raises(ConfigError, match=says):
        config.save(watchlist, section)
    assert watchlist.read_bytes() == before
    with pytest.raises(ConfigError, match=says):  # the page says the same
        App(watchlist).post_settings(section)
    assert watchlist.read_bytes() == before


def test_a_literal_brace_in_the_chat_prompt(watchlist):
    write(watchlist, chat={"prompt": "Answer as JSON like {{\"jobs\": []}}. {today}\n{context}"})
    text = chat.system_prompt("DATA", template=config.load(watchlist).chat.prompt)
    assert text.startswith('Answer as JSON like {"jobs": []}.') and text.endswith("DATA")


def test_settings_round_trip_through_the_page(watchlist):
    app = App(watchlist)
    s = app.get_settings({})
    assert s["chat"] == {} and s["pay"] == {} and s["suggestions"] == {} and s["alerts"] == {}
    assert s["defaults"] == config.defaults()
    assert s["chat_prompt"] == {"default": chat.SYSTEM, "text": chat.SYSTEM, "edited": False,
                                "placeholders": ["today", "context"]}
    assert (s["state"], s["cache"]) == ("state.db", "cache")  # shown, not edited
    imap = {"host": "imap.example.com", "user": "dana@example.com", "password_env": "JOBWATCH_TEST_IMAP",
            "port": 993, "folder": "Jobs", "days": 7, "senders": ["alerts@acme-robotics.example", "builtin.com"]}
    app.post_settings({
        "scoring": {"backend": "local", "model": "mlx-community/Tiny-Test-4bit", "top": 3, "auto": False},
        "chat": {"backend": "claude", "claude_model": "claude-test-model", "max_tokens": 800, "max_turns": 6,
                 "prompt": PROMPT},
        "pay": {"levels": True, "years": 9, "region": "test-metro-area", "ask_over": 12.5, "round": 1000,
                "today": 4},
        "suggestions": {"half_life": 45, "limit": 6},
        "learning": {"timeline": "month", "near": "Boulder", "jobs": 3},
        "alerts": {"imap": imap},
        "filters": {"titles": ["engineer"], "exclude_departments": ["sales"], "flags": {"TS/SCI": "clearance"}},
    })
    s = app.get_settings({})
    assert s["scoring"] == {"backend": "local", "model": "mlx-community/Tiny-Test-4bit", "top": 3, "auto": False}
    assert s["chat"]["max_turns"] == 6 and s["chat_prompt"]["edited"] and s["chat_prompt"]["text"] == PROMPT
    assert s["pay"]["ask_over"] == 12.5 and s["suggestions"] == {"half_life": 45, "limit": 6}
    assert s["learning"]["jobs"] == 3 and s["alerts"]["imap"] == imap
    assert s["filters"]["exclude_departments"] == ["sales"] and s["filters"]["flags"] == {"TS/SCI": "clearance"}
    cfg = config.load(watchlist)
    assert (cfg.score_model, cfg.score_top, cfg.auto_score) == ("mlx-community/Tiny-Test-4bit", 3, False)
    assert (cfg.chat.backend, cfg.chat.model, cfg.chat.max_tokens, cfg.chat.prompt) == \
        ("claude", "claude-test-model", 800, PROMPT)
    assert (cfg.pay.ask_over, cfg.pay.round, cfg.pay.today, cfg.pay.region) == (12.5, 1000, 4, "test-metro-area")
    assert (cfg.suggest.half_life, cfg.suggest.limit, cfg.learn_jobs, cfg.near) == (45, 6, 3, "Boulder")
    assert cfg.imap.senders == ("alerts@acme-robotics.example", "builtin.com") and cfg.imap.folder == "Jobs"
    assert cfg.filters.exclude_departments == ["sales"] and cfg.filters.flags == {"TS/SCI": "clearance"}
    # The default prompt sent back as it is isn't saved: it stays the default, and follows jobwatch's updates.
    app.post_settings({"chat": {"backend": "claude", "prompt": chat.SYSTEM}})
    assert "prompt" not in yaml.safe_load(watchlist.read_text())["chat"]
    app.post_settings({"chat": None, "pay": None, "suggestions": None, "alerts": None})  # cleared: the defaults
    cfg = config.load(watchlist)
    assert cfg.chat == Chat(backend="local") and cfg.suggest == config.Suggestions() and cfg.imap is None


def test_the_chat_uses_its_settings(watchlist, web, fake_model):
    write(watchlist, chat={"backend": "local", "local_model": "mlx-community/Tiny-Test-4bit", "max_tokens": 321,
                           "max_turns": 3, "prompt": PROMPT})
    app = App(watchlist)
    app.post_fetch({})
    talk = [{"role": r, "content": f"message {i}"} for i, r in enumerate(["user", "assistant"] * 3 + ["user"])]
    info, pieces = app.chat({"messages": talk})
    assert "".join(pieces) == "Fine."
    assert (fake_model["backend"], fake_model["model"], fake_model["max_tokens"]) == \
        ("local", "mlx-community/Tiny-Test-4bit", 321)
    assert fake_model["system"].startswith("You help Dana Acme look for robotics jobs. Today is 20")
    assert "Today's matching jobs" in fake_model["system"]  # {context} filled in
    assert fake_model["system"].endswith("Keep it to three lines.")
    assert [m["content"] for m in fake_model["messages"]] == ["message 4", "message 5", "message 6"]
    assert info["model"] == "mlx-community/Tiny-Test-4bit" and info["local"] is True
    assert app.get_chat({}) == chat.where("local", "mlx-community/Tiny-Test-4bit")


def test_the_page_has_a_card_for_each_section(server):
    page = request(server, "GET", "/")[1].decode()
    for section in ("companies", "filters", "keywords", "today", "resume", "people", "prompts", "chat", "pay",
                    "alerts", "suggestions", "skills"):
        assert f'setCard("{section}"' in page
    assert 'id: "set-display"' in page and 'class: "snav"' in page  # the bar with a link to each, and Save
    assert "function promptFold(" in page and "s.chat_prompt" in page  # the chat prompt edits like the fit ones


def test_chat_where_names_the_model():
    assert chat.where("claude", "claude-test-model")["model"] == "claude-test-model"
    assert chat.where("claude")["model"] == Chat.claude_model and chat.where("local")["model"] == Chat.local_model
