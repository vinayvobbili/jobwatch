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


def test_the_claude_plugin_and_desktop_extension_move_with_the_release(release, tmp_path):
    """Their manifests carry the version, and each pins the package itself, which moves too; a pin on another
    package at the same version is left alone."""
    root = make_project(tmp_path)
    (root / "plugin" / ".claude-plugin").mkdir(parents=True)
    (root / "plugin" / ".claude-plugin" / "plugin.json").write_text('{"name": "acme-tool", "version": "1.2.3"}')
    (root / "plugin" / ".mcp.json").write_text('{"args": ["--from", "acme-tool==1.2.3", "acme-tool-mcp"]}')
    (root / "plugin" / "pyproject.toml").write_text(
        '[project]\nversion = "1.2.3"\ndependencies = ["acme-tool[mcp]==1.2.3"]\n')
    (root / "desktop").mkdir()
    (root / "desktop" / "manifest.json").write_text('{"manifest_version": "0.4", "version": "1.2.3"}')
    (root / "desktop" / "pyproject.toml").write_text(
        '[project]\nversion = "1.2.3"\ndependencies = ["acme-tool[mcp]==1.2.3", "other==1.2.3"]\n')
    files = release.version_files(root, "acme-tool")
    out = {str(f.relative_to(root)): release.bump(f.read_text(), f, "1.2.3", "1.3.0", "acme-tool") for f in files}
    assert '"version": "1.3.0"' in out["plugin/.claude-plugin/plugin.json"]
    assert "acme-tool==1.3.0" in out["plugin/.mcp.json"]
    plugin = out["plugin/pyproject.toml"]
    assert 'version = "1.3.0"' in plugin and "acme-tool[mcp]==1.3.0" in plugin
    assert '"manifest_version": "0.4", "version": "1.3.0"' in out["desktop/manifest.json"]
    desktop = out["desktop/pyproject.toml"]
    assert 'version = "1.3.0"' in desktop and "acme-tool[mcp]==1.3.0" in desktop and "other==1.2.3" in desktop


def test_server_json_is_optional(release, tmp_path):
    root = make_project(tmp_path, server=False)
    assert [f.name for f in release.version_files(root, "acme-tool")] == ["pyproject.toml", "__init__.py"]


def test_an_init_that_reads_installed_metadata_is_left_alone(release, tmp_path):
    root = make_project(tmp_path, server=False)
    (root / "acme_tool" / "__init__.py").write_text(
        'from importlib.metadata import version\n\n__version__ = version("acme-tool")\n')
    assert [f.name for f in release.version_files(root, "acme-tool")] == ["pyproject.toml"]


def test_a_drifted_init_is_set_to_the_new_version_and_said_so(release, tmp_path):
    root = make_project(tmp_path, server=False)
    init = root / "acme_tool" / "__init__.py"
    init.write_text('__version__ = "1.2.0"\n')
    assert release.drift(release.version_files(root, "acme-tool"), "1.2.3") == ["__init__.py said 1.2.0, not 1.2.3"]
    assert release.bump(init.read_text(), init, "1.2.3", "1.3.0") == '__version__ = "1.3.0"\n'


def test_a_hatch_dynamic_version_is_read_and_bumped_where_hatch_reads_it(release, tmp_path):
    # The distribution's name isn't the package's (acme-tool-cli ships `acme`), and pyproject has no version.
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "acme-tool-cli"\ndynamic = ["version"]\n\n'
                                             '[tool.hatch.version]\npath = "src/acme/__init__.py"\n')
    pkg = tmp_path / "src" / "acme"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "0.4.0"\n')
    assert release.current_version(tmp_path) == "0.4.0"
    assert release.version_files(tmp_path, "acme-tool-cli") == [pkg / "__init__.py"]


def test_no_version_anywhere_stops_the_release(release, tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "acme-tool"\ndynamic = ["version"]\n')
    with pytest.raises(SystemExit, match="no version"):
        release.current_version(tmp_path)


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


def test_a_never_tagged_version_goes_out_as_declared_without_a_bump(release, tmp_path, monkeypatch, capsys):
    root = make_project(tmp_path)
    before = {p: p.read_text() for p in root.rglob("*") if p.is_file()}
    calls = []
    monkeypatch.setattr(release, "tagged", lambda root, tag: False)
    monkeypatch.setattr(release, "preflight", lambda root, tag: None)
    monkeypatch.setattr(release, "run_checks", lambda root: None)
    monkeypatch.setattr(release, "git", lambda root, *args: calls.append(args[0]) or "")
    monkeypatch.setattr(release.subprocess, "run", lambda *a, **k: calls.append("push"))
    assert release.main(["1.2.3", "--root", str(root), "--no-wait"]) == 0
    assert "acme-tool 1.2.3: not tagged yet" in capsys.readouterr().out
    assert calls == ["tag", "push"]  # no bump, so no commit
    assert {p: p.read_text() for p in root.rglob("*") if p.is_file()} == before


def test_a_tagged_version_is_still_refused(release, tmp_path, monkeypatch):
    root = make_project(tmp_path)
    monkeypatch.setattr(release, "tagged", lambda root, tag: True)
    with pytest.raises(SystemExit, match="isn't newer"):
        release.main(["1.2.3", "--dry-run", "--root", str(root)])


def test_root_releases_another_project(release, tmp_path, capsys):
    root = make_project(tmp_path, server=False)
    assert release.main(["2.0.0", "--dry-run", "--root", str(root)]) == 0
    assert "acme-tool 1.2.3 -> 2.0.0: pyproject.toml, acme_tool/__init__.py" in capsys.readouterr().out


def test_failed_checks_undo_the_bump(release, tmp_path, monkeypatch):
    root = make_project(tmp_path, server=False)
    before = {p: p.read_text() for p in root.rglob("*") if p.is_file()}
    monkeypatch.setattr(release, "preflight", lambda root, tag: None)

    def failing(root):
        raise release.subprocess.CalledProcessError(1, ["pytest"])

    monkeypatch.setattr(release, "run_checks", failing)
    monkeypatch.setattr(release, "git", lambda *a: pytest.fail("nothing is committed when the checks fail"))
    with pytest.raises(SystemExit, match="bump was undone"):
        release.main(["1.3.0", "--root", str(root)])
    assert {p: p.read_text() for p in root.rglob("*") if p.is_file()} == before


def test_checks_use_the_projects_own_virtualenv(release, tmp_path, monkeypatch):
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("")
    ran = []
    monkeypatch.setattr(release.subprocess, "run", lambda cmd, **kw: ran.append(cmd))
    release.run_checks(tmp_path)
    assert ran == [[str(venv / "python"), "-m", "pytest", "-q"]]


def test_published_checks_pypi_and_the_registry(release, monkeypatch):
    answers = {
        release.PYPI.format(name="acme-tool"): {"releases": {"1.2.3": [], "1.3.0": []}},
        release.REGISTRY.format(name="acme-tool"): {"servers": [
            {"server": {"name": "io.github.acme/acme-tool", "version": "1.2.3"}},
            {"server": {"name": "io.github.other/acme-tool", "version": "1.3.0"}}]},
    }
    monkeypatch.setattr(release, "fetch_json", lambda url: answers[url])
    assert release.published("acme-tool", "1.3.0", "io.github.acme/acme-tool") == \
        {"PyPI": True, "MCP Registry": False}
    assert release.published("acme-tool", "1.3.0", None) == {"PyPI": True}


def test_a_check_that_fails_says_why_instead_of_not_yet(release, monkeypatch, capsys):
    def fail(url):
        raise OSError("certificate verify failed")

    monkeypatch.setattr(release, "fetch_json", fail)
    seen = release.published("acme-tool", "1.3.0", "io.github.acme/acme-tool")
    assert seen == {"PyPI": "can't check: certificate verify failed",
                    "MCP Registry": "can't check: certificate verify failed"}
    assert release.wait_for("acme-tool", "1.3.0", "io.github.acme/acme-tool", timeout=0) is False
    assert "PyPI: can't check: certificate verify failed" in capsys.readouterr().out


def test_without_root_certificates_it_fetches_with_curl(release, monkeypatch):
    def no_certs(url, timeout):
        raise release.urllib.error.URLError(release.ssl.SSLCertVerificationError("unable to get local issuer"))

    calls = []

    def curl(cmd, **kw):
        calls.append(cmd)
        return release.subprocess.CompletedProcess(cmd, 0, stdout='{"releases": {"1.3.0": []}}', stderr="")

    monkeypatch.setattr(release.urllib.request, "urlopen", no_certs)
    monkeypatch.setattr(release.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(release.subprocess, "run", curl)
    assert release.fetch_json("https://pypi.org/pypi/acme-tool/json") == {"releases": {"1.3.0": []}}
    assert calls[0][0] == "curl" and calls[0][-1] == "https://pypi.org/pypi/acme-tool/json"


def test_other_network_errors_are_not_retried_with_curl(release, monkeypatch):
    def offline(url, timeout):
        raise release.urllib.error.URLError("nodename nor servname provided")

    monkeypatch.setattr(release.urllib.request, "urlopen", offline)
    monkeypatch.setattr(release.subprocess, "run", lambda *a, **k: pytest.fail("curl should not run"))
    with pytest.raises(release.urllib.error.URLError):
        release.fetch_json("https://pypi.org/pypi/acme-tool/json")
