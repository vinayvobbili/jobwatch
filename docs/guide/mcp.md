# MCP server

[← jobwatch guide](README.md)

`jobwatch-mcp` offers these tools to Claude Code or any MCP client:

- **Watchlist:** `find_board`, `list_boards`, `add_board`, `remove_board`, `list_suggested_boards`,
  `dismiss_suggested_board`
- **New jobs:** `fetch_jobs`, `import_job_alerts`, `get_digest`, `get_job`, `list_jobs`, `list_skill_gaps`
- **Applying:** `mark_job`, `list_queued_jobs`, `check_postings`, `add_application`, `list_applications`,
  `find_duplicates` (`get_job` and `list_queued_jobs` give each job's `duplicate_of`), `get_company`,
  `rate_contact`, `read_profile` (the roles on a LinkedIn experience page whose text you pasted: who the
  interviewer is; it never fetches linkedin.com)
- **What was sent:** `save_application_package`, `get_application_package`, `find_past_answers`,
  `get_interview_prep`, `save_story`

(0.3.0 renamed them to verb_noun: `digest` is now `get_digest`, `job_details` is `get_job`, `apply_queue` is
`list_queued_jobs`, `applications` is `list_applications`, `application_package` is `get_application_package`,
`interview_prep` is `get_interview_prep` and `skill_gaps` is `list_skill_gaps`.) The watchlist comes from
`JOBWATCH_CONFIG`:

```
claude mcp add jobwatch -s user -e JOBWATCH_CONFIG=~/jobwatch.yaml -- jobwatch-mcp
```

`jobwatch mcp` runs the same server. Without installing anything first,
[uv](https://docs.astral.sh/uv/) can fetch and run it:

```
claude mcp add jobwatch -s user -e JOBWATCH_CONFIG=~/jobwatch.yaml -- uvx --with 'mcp>=2.2' jobwatch mcp
```

It's listed in the [MCP Registry](https://registry.modelcontextprotocol.io) as `io.github.vinayvobbili/jobwatch`.

[plugin/skills/jobwatch/SKILL.md](../../plugin/skills/jobwatch/SKILL.md) is an agent skill that tells an assistant
when and how to use these tools (setup, the daily loop, status emails, interview prep, and what never to do for
you). Copy the folder into `~/.claude/skills/`, or zip it for a skills marketplace: `cd plugin/skills && python -m
zipfile -c jobwatch-skill.zip jobwatch`.

## Claude plugin and desktop extension

[plugin/](../../plugin) is a Claude plugin with the skill and the server together. In Claude Code:

```
/plugin marketplace add vinayvobbili/jobwatch
/plugin install jobwatch@jobwatch
```

In the Claude app, the same marketplace goes in through Settings → Plugins → Add → Add marketplace; the
server runs in the Code tab. Chat runs plugins in the cloud, where the skill loads but the server can't
reach your computer, so the tools aren't there.

Claude Desktop versions with Settings → Extensions take the desktop extension instead:
`jobwatch-<version>.mcpb` on the [releases page](https://github.com/vinayvobbili/jobwatch/releases). Open it and
choose Install; Claude Desktop sets up Python through uv, so nothing else needs installing.
`scripts/build-mcpb` builds it from [desktop/](../../desktop).

With a resume tool alongside it (for example [resume-kit](https://github.com/vinayvobbili/resume-kit), whose
`resume draft` starts a tailored version from a posting), an assistant can work through your queue: read
the posting, tailor the resume from facts you've confirmed, check for a referral, and fill in the
application for you to review. You still press Submit.
