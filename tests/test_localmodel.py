"""The local model suggested for this computer's memory: the RAM to model mapping, with detection mocked."""

import json
from pathlib import Path

import pytest

from jobwatch import localmodel
from jobwatch.localmodel import EIGHT_BIT, TIERS, billions, configured_model, nominal_gb, pick, recommend

from .conftest import TOKEN, request

GB = 2**30
ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("reported, installed", [
    (8 * GB, 8), (7.6 * GB, 8), (16 * GB, 16), (15.2 * GB, 16), (14.9 * GB, 16), (24 * GB, 24),
    (31.4 * GB, 32), (36 * GB, 36), (48 * GB, 48), (63 * GB, 64), (128 * GB, 128), (2 * GB, 4)])
def test_the_installed_size_is_found_from_what_the_system_reports(reported, installed):
    assert nominal_gb(int(reported)) == installed


@pytest.mark.parametrize("gb, name", [
    (4, "Qwen3.5-4B-MLX-4bit"), (8, "Qwen3.5-4B-MLX-4bit"), (12, "Qwen3.5-4B-MLX-4bit"),
    (16, "Qwen3.5-9B-MLX-4bit"), (18, "Qwen3.5-9B-MLX-4bit"),
    (24, "Qwen3.8-27B-4bit"), (32, "Qwen3.8-27B-4bit"), (36, "Qwen3.8-27B-4bit"),
    (48, "Qwen3.6-35B-A3B-4bit"), (64, "Qwen3.6-35B-A3B-8bit"), (128, "Qwen3.6-35B-A3B-8bit")])
def test_each_size_of_memory_gets_the_biggest_row_that_fits_with_8_bit_from_64_gb(gb, name):
    assert pick(gb).mlx == name


def test_the_row_boundaries_fall_at_16_24_and_48_gb():
    assert [pick(g).ram for g in (15, 16, 23, 24, 47, 48)] == [
        "8 GB", "16 GB", "16 GB", "24-32 GB", "24-32 GB", "48 GB and up"]
    assert pick(63) is TIERS[-1] and pick(64) is EIGHT_BIT


def test_only_the_16_gb_row_is_tested():
    assert [t.ram for t in TIERS if t.tested] == ["16 GB"]
    assert not EIGHT_BIT.tested


def test_apple_silicon_gets_an_mlx_repo_and_the_command_that_serves_it():
    r = recommend(total=16 * GB, apple=True)
    s = r["suggested"]
    assert (r["ram_gb"], r["system"]) == (16, "Apple Silicon")
    assert s["id"] == "mlx-community/Qwen3.5-9B-MLX-4bit" and s["tested"] and s["gb"] == 16
    assert s["command"] == "vllm-mlx serve mlx-community/Qwen3.5-9B-MLX-4bit --port 8010"
    assert s["link"] == "https://huggingface.co/mlx-community/Qwen3.5-9B-MLX-4bit"
    assert r["note"] == ""


def test_other_computers_get_an_ollama_tag(monkeypatch):
    monkeypatch.setattr(localmodel.sys, "platform", "linux")
    r = recommend(total=32 * GB, apple=False)
    s = r["suggested"]
    assert r["system"] == "Linux" and not r["apple"]
    assert s["id"] == "qwen3.8:27b-q4_K_M" and s["command"] == "ollama pull qwen3.8:27b-q4_K_M"
    assert not s["tested"] and s["link"] == "https://ollama.com/library/qwen3.8"
    assert "LOCAL_LLM_URL=http://127.0.0.1:11434/v1" in r["note"]
    assert [row["id"] for row in r["rows"]] == [t.tag for t in TIERS]


def test_an_intel_mac_is_not_apple_silicon(monkeypatch):
    monkeypatch.setattr(localmodel.sys, "platform", "darwin")
    assert localmodel.system_name(False) == "Intel Mac" and localmodel.system_name(True) == "Apple Silicon"


def test_a_64_gb_computer_is_suggested_the_8_bit_build():
    assert recommend(total=64 * GB, apple=True)["suggested"]["id"] == "mlx-community/Qwen3.6-35B-A3B-8bit"
    assert recommend(total=64 * GB, apple=False)["suggested"]["id"] == "qwen3.6:35b-a3b-q8_0"
    assert recommend(total=48 * GB, apple=False)["suggested"]["id"] == "qwen3.6:35b-a3b-q4_K_M"


def test_unknown_memory_gives_the_table_and_no_suggestion(monkeypatch):
    monkeypatch.setattr(localmodel, "ram_bytes", lambda: None)
    r = recommend(apple=True)
    assert r["suggested"] is None and r["ram_gb"] is None and len(r["rows"]) == 4


def test_detection_is_asked_when_nothing_is_given(monkeypatch):
    monkeypatch.setattr(localmodel, "ram_bytes", lambda: 16 * GB)
    monkeypatch.setattr(localmodel, "is_apple_silicon", lambda: True)
    assert recommend()["suggested"]["row"] == "16 GB"


def test_the_system_reports_its_memory_in_a_way_that_is_read(monkeypatch, tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       16384000 kB\nMemFree: 1 kB\n")
    monkeypatch.setattr(localmodel.sys, "platform", "linux")
    monkeypatch.setattr(localmodel, "Path", lambda p: meminfo)
    assert localmodel.ram_bytes() == 16384000 * 1024
    monkeypatch.setattr(localmodel.sys, "platform", "darwin")
    monkeypatch.setattr(localmodel.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "17179869184\n"})())
    assert localmodel.ram_bytes() == 16 * GB


@pytest.mark.parametrize("model, size", [
    ("mlx-community/Qwen3.5-9B-MLX-4bit", 9), ("Qwen3.6-35B-A3B-4bit", 35), ("qwen3.5:4b-q4_K_M", 4),
    ("qwen3.6:35b-a3b-q8_0", 35), ("gemma-4-12B-it-4bit", 12), ("some-model", 0)])
def test_a_models_size_is_read_from_its_id(model, size):
    assert billions(model) == size


def test_a_model_set_already_is_only_noted_when_larger_than_suggested():
    small = recommend("mlx-community/Qwen3.5-9B-MLX-4bit", total=16 * GB, apple=True)["configured"]
    big = recommend("mlx-community/Qwen3.8-27B-4bit", total=16 * GB, apple=True)["configured"]
    assert small == {"model": "mlx-community/Qwen3.5-9B-MLX-4bit", "larger": False}
    assert big["larger"] is True
    assert recommend("", total=16 * GB, apple=True)["configured"] is None
    assert recommend("x", total=16 * GB, apple=True)["configured"] == {"model": "x", "larger": False}


def test_the_configured_model_comes_from_the_scoring_settings():
    assert configured_model({"backend": "local", "model": "m1"}, "dflt") == "m1"
    assert configured_model({"backend": "local"}, "dflt") == "dflt"
    assert configured_model({"backend": "claude", "fallback": ["agy", "local:m2"]}, "dflt") == "m2"
    assert configured_model({"backend": "claude", "fallback": ["local"]}, "dflt") == "dflt"
    assert configured_model({"backend": "claude", "fallback": ["agy"]}, "dflt") == ""
    assert configured_model({}, "dflt") == ""


def test_the_home_page_and_the_guide_show_every_model_of_the_table():
    site = (ROOT / "site/index.html").read_text(encoding="utf-8")
    guide = (ROOT / "docs/guide/fit-scores.md").read_text(encoding="utf-8")
    for t in [*TIERS, EIGHT_BIT]:
        for text in (site, guide):
            assert t.mlx in text and t.tag in text
            assert f"https://huggingface.co/mlx-community/{t.mlx}" in text
            assert f"https://ollama.com/library/{t.tag}" in text
    assert "tested on a 16 GB Mac" in site
    for t in [*TIERS, EIGHT_BIT]:
        for text in (site, guide):
            assert f"https://huggingface.co/mlx-community/{t.alt.mlx}" in text
            assert f"https://ollama.com/library/{t.alt.tag}" in text
    assert "Also good: Gemma 4" in site and "Also good: Gemma 4" in guide
    for text in (site, guide):
        assert "Mac with Apple Silicon (MLX, runs on the GPU via Metal)" in text
        assert "Windows, Linux or Intel Mac (Ollama)" in text
        assert text.index("Mac with Apple Silicon (MLX") < text.index("Windows, Linux or Intel Mac (Ollama)")
        assert ("On an Apple Silicon Mac, use MLX: it's built for Apple's chips and runs faster than Ollama there."
                in " ".join(text.split()))
    assert "about 50% slower" in site and "about 50% slower" in guide


def test_every_row_has_a_gemma_4_beside_its_qwen():
    assert [t.alt.mlx for t in TIERS] == [
        "gemma-4-e2b-it-4bit", "gemma-4-12B-it-4bit", "gemma-4-26b-a4b-it-4bit", "gemma-4-31b-it-4bit"]
    assert [t.alt.tag for t in TIERS] == [
        "gemma4:e2b-it-q4_K_M", "gemma4:12b-it-q4_K_M", "gemma4:26b-a4b-it-q4_K_M", "gemma4:31b-it-q4_K_M"]
    assert all(t.alt.tag.endswith("q4_K_M") and t.alt.mlx.endswith("4bit") for t in TIERS)
    assert [bool(t.alt.note) for t in TIERS] == [False, True, False, False]  # only the 16 GB row's was measured
    assert "29/29 vs 28/29" in TIERS[1].alt.note and "about 50% slower" in TIERS[1].alt.note


def test_the_alternative_is_served_like_the_suggestion_and_shown_with_every_row():
    r = recommend(total=16 * GB, apple=True)
    alt = r["suggested"]["alt"]
    assert alt["id"] == "mlx-community/gemma-4-12B-it-4bit"
    assert alt["command"] == "vllm-mlx serve mlx-community/gemma-4-12B-it-4bit --port 8010"
    assert alt["link"] == "https://huggingface.co/mlx-community/gemma-4-12B-it-4bit"
    assert r["rows"][0]["alt"]["id"] == "mlx-community/gemma-4-e2b-it-4bit"
    assert all(row["alt"] for row in r["rows"])
    other = recommend(total=16 * GB, apple=False)["suggested"]["alt"]
    assert other["command"] == "ollama pull gemma4:12b-it-q4_K_M"
    assert other["link"] == "https://ollama.com/library/gemma4:12b-it-q4_K_M"
    assert recommend(total=64 * GB, apple=True)["suggested"]["alt"]["id"] == "mlx-community/gemma-4-31b-it-4bit"


def test_the_ai_endpoint_carries_the_suggestion_and_the_model_set(server, watchlist, monkeypatch):
    monkeypatch.setattr(localmodel, "ram_bytes", lambda: 32 * GB)
    monkeypatch.setattr(localmodel, "is_apple_silicon", lambda: True)
    watchlist.write_text(watchlist.read_text()
                         + "scoring:\n  backend: local\n  model: mlx-community/Qwen3.5-9B-MLX-4bit\n")
    status, data = request(server, "GET", "/api/ai", headers={"X-Jobwatch-Token": TOKEN})
    rec = json.loads(data)["local"]["recommend"]
    assert status == 200
    assert rec["suggested"]["id"] == "mlx-community/Qwen3.8-27B-4bit" and rec["suggested"]["gb"] == 32
    assert rec["configured"] == {"model": "mlx-community/Qwen3.5-9B-MLX-4bit", "larger": False}
