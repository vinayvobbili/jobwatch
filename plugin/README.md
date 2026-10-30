# jobwatch

Run your job search from a conversation with Claude. Name the companies you'd like to work for, and jobwatch
watches their job boards (Greenhouse, Lever, Ashby, Workable, Workday, Eightfold, Rippling, Google Careers,
Amazon, Oracle, SmartRecruiters, Avature, iCIMS, Jobvite and Hacker News' monthly "Who is hiring?"), ranks
the new roles that match what you're looking for, and keeps track of every application from the day you apply
to the offer. It never applies for you: Claude fills in what it can and you press Submit.

The plugin bundles jobwatch's MCP server (its tools) and a skill that tells Claude the daily routine: what to
check, what to show you first, and what never to do without you.

## Use it

Ask Claude things like:

- "Watch Stripe and these three careers pages for product designer roles in Chicago or remote."
- "What's new today?" Claude checks every board and shows the best few matches, with why each fits.
- "Queue the second one." Then, after you apply: "I applied to it."
- "Here's the recruiter's email, update my tracker." Claude proposes the change and waits for your yes.
- "Get me ready for Thursday's interview." Claude puts the posting, your resume and what you sent on one sheet.

The first time, Claude asks which companies to watch and creates your watchlist.

## Install

Claude Code: `/plugin marketplace add vinayvobbili/jobwatch`, then `/plugin install jobwatch@jobwatch`.
The server runs with [uv](https://docs.astral.sh/uv/) (`uvx`), which downloads jobwatch from PyPI on first
use. In Claude Desktop's chat, which doesn't start local servers from plugins, install the jobwatch desktop
extension (`jobwatch-<version>.mcpb` from the
[releases page](https://github.com/vinayvobbili/jobwatch/releases)) for the tools.

## Your data

Everything jobwatch keeps stays on your computer: the watchlist file (by default
`~/.config/jobwatch/config.yaml`, set in the plugin's options), the tracker database in
`~/.local/share/jobwatch/`, and a cache in `~/.cache/jobwatch/`. Nothing is sent to the plugin's author or any
analytics service.

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
