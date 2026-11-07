"""Build the skills-only plugin the Claude directory lists from the full plugin.

The directory takes a local MCP server, and any file other than Markdown, text, JSON, YAML or an image, only from
Verified organizations. So its copy is the full plugin without the server: the skills, the license, the icon, the
manifest without the server's options, and plugin-skill/README.md (committed: how to add the tools). On the
`directory` branch, scripts/directory-branch moves the full plugin to plugin-full/ (the marketplace installs it from
there) and writes this copy to plugin/, the folder the directory submission follows.

    python3 scripts/skill_plugin.py SRC README DEST    # e.g. plugin-full plugin-skill/README.md plugin
"""

import json
import shutil
import sys
from pathlib import Path

IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico"}
ALLOWED = {".md", ".txt", ".json", ".yaml", ".yml"} | IMAGES
NAMED = {"LICENSE"}  # no extension, but plain text the directory lets through
SERVER_ONLY = ("userConfig",)  # manifest fields that only configure the MCP server


def build(src: Path, readme: Path, dest: Path) -> Path:
    """Write DEST (replacing it) from the full plugin SRC, with README as its README.md; returns DEST."""
    text = readme.read_text(encoding="utf-8")
    shutil.rmtree(dest, ignore_errors=True)
    (dest / ".claude-plugin").mkdir(parents=True)
    (dest / "README.md").write_text(text, encoding="utf-8")
    shutil.copytree(src / "skills", dest / "skills")
    for name in ("LICENSE", "icon.png"):
        shutil.copy2(src / name, dest / name)
    manifest = json.loads((src / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    for key in SERVER_ONLY:
        manifest.pop(key, None)
    (dest / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                                         encoding="utf-8")
    if bad := refused(dest):
        raise SystemExit(f"{dest} would be refused by the directory: {', '.join(bad)}")
    return dest


def refused(folder: Path) -> list[str]:
    """Files the directory refuses from an organization that isn't Verified: a type outside the allowed ones, a
    script (#!), text that isn't UTF-8 or has a NUL byte, and an MCP server."""
    bad = []
    for p in sorted(x for x in folder.rglob("*") if x.is_file()):
        name = str(p.relative_to(folder))
        if p.suffix.lower() not in ALLOWED and p.name not in NAMED:
            bad.append(f"{name} (file type)")
        elif p.suffix.lower() not in IMAGES:
            data = p.read_bytes()
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                bad.append(f"{name} (not UTF-8)")
                continue
            if data.startswith(b"#!") or b"\0" in data:
                bad.append(f"{name} (script or NUL byte)")
    if (folder / ".mcp.json").exists() or "mcpServers" in (folder / ".claude-plugin" / "plugin.json").read_text():
        bad.append("an MCP server")
    return bad


if __name__ == "__main__":
    print(build(*(Path(a) for a in sys.argv[1:4])))
