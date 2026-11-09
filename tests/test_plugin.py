"""The Claude plugin (plugin/) and the Claude Desktop extension (desktop/): both run the release they pin, and the
plugin folder passes what the Claude directory checks before a human looks (README, license, file kinds)."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# The full plugin: plugin/ on main, plugin-full/ on the directory branch (where plugin/ is the skills-only copy)
PLUGIN = ROOT / "plugin-full" if (ROOT / "plugin-full").is_dir() else ROOT / "plugin"
DESKTOP = ROOT / "desktop"
VERSION = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)


def test_the_plugin_runs_the_released_server_pinned_to_this_version():
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    server = json.loads((PLUGIN / ".mcp.json").read_text())["mcpServers"]["jobwatch"]
    assert manifest["name"] == "jobwatch" and manifest["version"] == VERSION
    # the directory's locked launch (its Verified badge) takes `uvx --from <package>==<version>`, no extra
    assert server["command"] == "uvx" and server["args"] == ["--from", f"jobwatch=={VERSION}", "jobwatch-mcp"]
    base = re.search(r"^dependencies = \[(.*)\]", (ROOT / "pyproject.toml").read_text(), re.M).group(1)
    assert '"mcp>=' in base  # so plain jobwatch runs jobwatch-mcp
    # the watchlist the person sets in the plugin's options reaches the server
    assert server["env"]["JOBWATCH_CONFIG"] == "${user_config.watchlist}" and "watchlist" in manifest["userConfig"]


def test_the_marketplace_installs_the_plugin_folder_as_released():
    """`/plugin marketplace add` reads the marketplace from main, but the plugin itself comes from the
    `directory` branch's plugin-full/, the full plugin as released (its plugin/ is the Claude directory's
    skills-only copy). An https URL: `owner/repo` would clone over SSH, which fails for anyone without a GitHub
    SSH key."""
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert [(p["name"], p["source"]) for p in market["plugins"]] == [
        ("jobwatch", {"source": "git-subdir", "url": "https://github.com/vinayvobbili/jobwatch.git",
                      "path": "plugin-full", "ref": "directory"})]
    script = (ROOT / "scripts" / "directory-branch").read_text()
    assert "mv plugin plugin-full" in script


def test_the_plugin_folder_has_what_the_directory_requires():
    readme = (PLUGIN / "README.md").read_text()
    prose = re.sub(r"```.*?```", "", readme, flags=re.S)
    assert len(prose.split()) >= 40 and (PLUGIN / "LICENSE").is_file()
    files = [p for p in PLUGIN.rglob("*") if p.is_file() and "evals" not in p.relative_to(PLUGIN).parts[:1]]
    assert not [p.name for p in files if p.name in (".DS_Store", "Thumbs.db", "desktop.ini")]
    assert not [p.name for p in files if p.suffix not in (".json", ".md", ".png", ".yaml", ".toml", ".lock", "") or
                (p.suffix != ".png" and p.stat().st_size > 256 * 1024)]
    assert not (PLUGIN / "bin").exists()  # a top-level bin/ stops claude.ai and Cowork installing it


def test_the_skills_only_plugin_has_only_what_the_directory_takes_from_anyone(tmp_path):
    """The Claude directory takes a local MCP server, and files other than Markdown, text, JSON, YAML and images,
    only from Verified organizations: its copy is the skill, license, icon and manifest, with no server."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("skill_plugin", ROOT / "scripts" / "skill_plugin.py")
    skill_plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(skill_plugin)
    full_plugin = shutil.copytree(PLUGIN, tmp_path / "plugin-full")
    (full_plugin / "uv.lock").write_text("version = 1\n")  # on the directory branch it's there too
    out = skill_plugin.build(full_plugin, ROOT / "plugin-skill" / "README.md", tmp_path / "plugin")
    files = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())
    assert files == [".claude-plugin/plugin.json", "LICENSE", "README.md", "icon.png", "skills/jobwatch/LICENSE",
                     "skills/jobwatch/SKILL.md"]
    assert skill_plugin.refused(out) == []
    full = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    full.pop("userConfig")
    assert json.loads((out / ".claude-plugin" / "plugin.json").read_text()) == full  # same name, version, listing
    assert (out / "skills/jobwatch/SKILL.md").read_bytes() == (PLUGIN / "skills/jobwatch/SKILL.md").read_bytes()
    assert "claude mcp add jobwatch" in (out / "README.md").read_text()  # how to add the tools
    # the full plugin would be refused: its server and its lock
    assert {"an MCP server", "pyproject.toml (file type)", "uv.lock (file type)"} <= set(skill_plugin.refused(
        full_plugin))
    assert "skill_plugin.py" in (ROOT / "scripts" / "directory-branch").read_text()


def test_the_directory_branch_moves_only_with_a_release():
    """The Claude directory follows the `directory` branch; only the release workflow moves it, after the
    release (and its desktop extension) is out."""
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    job = workflow.split("\n  directory-branch:\n", 1)[1]
    assert "needs: desktop-extension" in job and 'scripts/directory-branch "$GITHUB_SHA"' in job
    other = [p for p in (ROOT / ".github" / "workflows").glob("*.yml") if p.name != "release.yml"]
    assert not [p.name for p in other if "directory-branch" in p.read_text()]
    script = (ROOT / "scripts" / "directory-branch").read_text()
    assert "uv lock" in script and "add --force plugin/uv.lock" in script and "refs/heads/directory" in script


def test_the_plugin_locks_the_server_it_runs():
    """plugin/pyproject.toml pins what .mcp.json runs. Its uv.lock is committed only on the directory branch,
    since it can be written only once PyPI has the release; where it's committed, it locks this release and
    fits the directory's 256 KiB file limit."""
    env = (PLUGIN / "pyproject.toml").read_text()
    assert f'version = "{VERSION}"' in env and f'dependencies = ["jobwatch=={VERSION}"]' in env
    assert "plugin/uv.lock" in (ROOT / ".gitignore").read_text().splitlines()
    tracked = subprocess.run(["git", "ls-files", PLUGIN.name], cwd=ROOT, capture_output=True, text=True).stdout
    if f"{PLUGIN.name}/uv.lock" in tracked.split():
        lock = PLUGIN / "uv.lock"
        assert f'name = "jobwatch"\nversion = "{VERSION}"\n' in lock.read_text()
        assert lock.stat().st_size <= 256 * 1024


def test_the_desktop_extension_runs_the_released_server_with_uv():
    manifest = json.loads((DESKTOP / "manifest.json").read_text())
    assert manifest["manifest_version"] == "0.4" and manifest["version"] == VERSION
    server = manifest["server"]
    assert server["type"] == "uv" and (DESKTOP / server["entry_point"]).is_file()
    assert server["mcp_config"]["args"][-1] == server["entry_point"]
    assert server["mcp_config"]["env"]["JOBWATCH_CONFIG"] == "${user_config.watchlist}"
    env = (DESKTOP / "pyproject.toml").read_text()
    assert f'version = "{VERSION}"' in env and f'"jobwatch=={VERSION}"' in env
    assert not (DESKTOP / "server" / "lib").exists()  # the uv type installs dependencies; none are bundled


def test_the_desktop_bundle_retries_past_a_cached_index_page():
    """The release's bundle check waits for PyPI to serve the release, with uv's cache off: a cached index page
    from before the upload would make every retry miss it (v0.9.0's five did)."""
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    job = workflow.split("\n  desktop-extension:\n", 1)[1].split("\n  directory-branch:\n", 1)[0]
    step = job.split("- name: Build and check the bundle", 1)[1].split("- name:", 1)[0]
    assert 'UV_NO_CACHE: "1"' in step and "sleep 60" in step


@pytest.mark.skipif(not shutil.which("claude"), reason="needs Claude Code's `claude plugin validate`")
def test_claude_code_validates_the_plugin_and_the_marketplace():
    for target in (PLUGIN, ROOT):
        done = subprocess.run(["claude", "plugin", "validate", str(target)], capture_output=True, text=True)
        assert done.returncode == 0, done.stdout + done.stderr
