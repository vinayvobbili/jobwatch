"""scripts/release.py: the version bump and the publish check. Nothing here runs git or reaches the network."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release.py"


@pytest.fixture
def release():
    spec = importlib.util.spec_from_file_location("release", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_project(root: Path, *, src=False, server=True) -> Path:
    (root / "pyproject.toml").write_text('[project]\nname = "acme-tool"\nversion = "1.2.3"\n')
    pkg = (root / "src" if src else root) / "acme_tool"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('"""Acme."""\n\n__version__ = "1.2.3"\n')
    if server:
        (root / "server.json").write_text(json.dumps({
            "name": "io.github.acme/acme-tool", "version": "1.2.3",
            "packages": [{"registryType": "pypi", "identifier": "acme-tool", "version": "1.2.3"}],
        }, indent=2))
    return root


@pytest.mark.parametrize("src", [False, True])
def test_bumps_every_file_that_declares_the_version(release, tmp_path, src):
    root = make_project(tmp_path, src=src)
    assert release.project_name(root) == "acme-tool" and release.current_version(root) == "1.2.3"
    files = release.version_files(root, "acme-tool")
    assert [f.name for f in files] == ["pyproject.toml", "__init__.py", "server.json"]
    out = {f.name: release.bump(f.read_text(), f, "1.2.3", "1.3.0") for f in files}
    assert 'version = "1.3.0"' in out["pyproject.toml"]
    assert '__version__ = "1.3.0"' in out["__init__.py"]
    server = json.loads(out["server.json"])
    assert server["version"] == server["packages"][0]["version"] == "1.3.0"


def test_server_json_is_optional(release, tmp_path):
    root = make_project(tmp_path, server=False)
    assert [f.name for f in release.version_files(root, "acme-tool")] == ["pyproject.toml", "__init__.py"]


def test_a_file_without_the_old_version_stops_the_release(release, tmp_path):
    f = tmp_path / "pyproject.toml"
    f.write_text('version = "1.2.4"\n')
    with pytest.raises(SystemExit, match=r"doesn't declare version 1\.2\.3"):
        release.bump(f.read_text(), f, "1.2.3", "1.3.0")


def test_dry_run_changes_nothing_and_older_versions_are_refused(release, tmp_path, monkeypatch, capsys):
    root = make_project(tmp_path)
    monkeypatch.setattr(release, "ROOT", root)
    before = {p: p.read_text() for p in root.rglob("*") if p.is_file()}
    assert release.main(["1.3.0", "--dry-run"]) == 0
    assert "acme-tool 1.2.3 -> 1.3.0" in capsys.readouterr().out
    assert {p: p.read_text() for p in root.rglob("*") if p.is_file()} == before
    for bad in ("1.2.3", "1.1.9", "1.3"):
        with pytest.raises(SystemExit):
            release.main([bad, "--dry-run"])


def test_published_checks_pypi_and_the_registry(release, monkeypatch):
    answers = {
        release.PYPI.format(name="acme-tool"): {"releases": {"1.2.3": [], "1.3.0": []}},
        release.REGISTRY.format(name="io.github.acme/acme-tool"): {"servers": [
            {"server": {"name": "io.github.acme/acme-tool", "version": "1.2.3"}}]},
    }
    monkeypatch.setattr(release, "fetch_json", lambda url: answers[url])
    assert release.published("acme-tool", "1.3.0", "io.github.acme/acme-tool") == \
        {"PyPI": True, "MCP Registry": False}
    assert release.published("acme-tool", "1.3.0", None) == {"PyPI": True}
