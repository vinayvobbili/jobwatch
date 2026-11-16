# jobwatch

Run your job search from a conversation with Claude. Name the companies you'd like to work for, and jobwatch
watches their job boards (Greenhouse, Lever, Ashby, Workable, Workday, Eightfold, Rippling, Google Careers,
Amazon, Oracle, SmartRecruiters, Avature, iCIMS, Jobvite, careers sites with a job sitemap and Hacker News' monthly "Who is hiring?"), ranks
the new roles that match what you're looking for, and keeps track of every application from the day you apply
to the offer. It never applies for you: Claude fills in what it can and you press Submit.

This plugin is jobwatch's skill: it tells Claude the daily routine (what to check, what to show you first, and
what never to do without you). The tools that do the work come from jobwatch's MCP server, which runs on your
computer, so your job search stays there. The first time, Claude offers to add it for you.

## Use it

Ask Claude things like:

- "Watch Stripe and these three careers pages for product designer roles in Chicago or remote."
- "What's new today?" Claude checks every board and shows the best few matches, with why each fits.
- "Queue the second one." Then, after you apply: "I applied to it."
- "Here's the recruiter's email, update my tracker." Claude proposes the change and waits for your yes.
- "Get me ready for Thursday's interview." Claude puts the posting, your resume and what you sent on one sheet.

The first time, Claude asks which companies to watch and creates your watchlist.

## Add the tools

First install [uv](https://docs.astral.sh/uv/getting-started/installation/), once: on a Mac or Linux, in
Terminal, `curl -LsSf https://astral.sh/uv/install.sh | sh` (or `brew install uv`); on Windows, in PowerShell,
`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`. Then, in Claude Code (or
the Claude app's Code tab), add jobwatch's server and restart Claude:

```
claude mcp add jobwatch -s user -e JOBWATCH_CONFIG=~/.config/jobwatch/config.yaml -- uvx --from jobwatch jobwatch-mcp
```

Or install the plugin with the server built in instead of this one: `/plugin marketplace add vinayvobbili/jobwatch`,
then `/plugin install jobwatch@jobwatch`. Claude Desktop versions with Settings → Extensions can install the
jobwatch desktop extension (`jobwatch-<version>.mcpb` from the
[releases page](https://github.com/vinayvobbili/jobwatch/releases)). A chat whose plugins run in the cloud has
the skill but not the tools, because they can't reach your computer: use the Code tab or Cowork.

## Your data

Everything jobwatch keeps stays on your computer: the watchlist file (`~/.config/jobwatch/config.yaml` in the
command above), the tracker database in `~/.local/share/jobwatch/`, and a cache in `~/.cache/jobwatch/`. Nothing
is sent to the plugin's author or any analytics service.

What it fetches over the network:

- The public job-board pages and APIs of the companies on your watchlist, and Hacker News through
  `hn.algolia.com`. These requests carry no personal data, only the company's board name.
- PyPI, once, when `uvx` installs jobwatch.
- Only if you turn them on in the watchlist: pay data from Levels.fyi, and fit scores, which send a posting and
  your resume to the model you choose there (an on-device model on Apple Silicon by default; Claude through
  your own API key, or Google's agy command-line tool).

Emails reach jobwatch only when you ask Claude to read them with a mail connector you added; jobwatch never
asks for your mail password.

## Learn more

The [guide](https://github.com/vinayvobbili/jobwatch/tree/main/docs/guide) covers the watchlist, the daily
digest, the tracker and interview prep. jobwatch is open source (MIT) at
[github.com/vinayvobbili/jobwatch](https://github.com/vinayvobbili/jobwatch).
