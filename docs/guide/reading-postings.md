# Reading postings by itself

Jobs that come from a LinkedIn or Indeed alert or list arrive with a title, a company and a place, but no posting text.
Without the text jobwatch can't score the job, show its requirements or tailor a resume. LinkedIn and Indeed show a
posting only to a signed-in browser, so jobwatch can't fetch it. The **Read posting** button on a job's card gets
around that by opening the job in your own browser, where you are signed in, and having the
[browser extension](../../chrome-extension/README.md) copy the text. **Read postings automatically** does the same
thing without you pressing the button, one job at a time, slowly, and only for the jobs worth reading.

It is off until you turn it on. Read the risk first.

## The risk

**LinkedIn may restrict accounts that look automated. These limits keep reading slow and small; you can turn it off
anytime.** Both sites' terms discourage automated access. jobwatch's reading is built to look like a person opening a
few job pages in a quiet tab, and it stops for the day at the first sign of trouble, but it can't promise that a site
will never object. If your LinkedIn account matters more to you than a few postings read for you, leave this off and
press **Read posting** on the jobs you care about.

## What it does

When it is on, the extension asks jobwatch every few minutes which job to read next. jobwatch picks it, not the
extension:

- a job that passes your title, place, pay and fit filters (what Today shows), best first;
- with no posting text yet, and not closed, a duplicate, snoozed, skipped or read recently;
- at a company whose own job board jobwatch doesn't already watch (a job on a board gets its text from there).

The extension then opens that job's page in a tab behind the one you are using, copies the posting to jobwatch and
closes the tab. The text is saved exactly as **Read posting** saves it. Scoring follows your usual scoring settings
(automatic scoring and its caps); reading never forces a score.

## The limits

These are the defaults. Each can be tightened in Settings > Applying > Read postings automatically, and loosened only
up to a hard ceiling that no setting can pass.

- One job at a time, never two tabs, one page load per job. It doesn't scroll, click or follow a link.
- A random pause of 2 to 3 minutes between two reads (never under 1 minute, whatever the setting).
- At most 25 reads a day for each site, and never more than 50 a day for LinkedIn and Indeed together. The day is your
  local day; a restart of Chrome or the computer doesn't reset the count.
- Only while Chrome is open, and not while you are using a LinkedIn or Indeed tab. Come back from a break or switch to
  another tab and it reads again.

## When it stops

At the first sign of trouble it stops for the rest of the day: a sign-in page or a "sign in to see this" wall, a
CAPTCHA or security check, "unusual activity", an HTTP error 429, 999 or 403, an account restriction notice, or two
pages in a row with no posting on them. The extension's badge shows "!", and the side panel and Today say why:

Auto-read paused: LinkedIn asked for a sign-in. Resumes tomorrow, or press Resume after you check LinkedIn.

The tab that showed the trouble is left open so you can look at it. Sign in or solve the check yourself, then press
**Resume** if you want it to go on today. It never signs in or solves a check for you.

## Watching it and turning it off

- Today shows a line such as "Reading postings: 3 of 12 today · next in 2m" with **Pause**, **Resume** and **Off**.
  The extension's side panel shows the same line and buttons.
- Activity lists every read ("Read Platform Engineer at Initech from linkedin.com"), every job it couldn't read and why,
  and every pause, resume and stop.
- **Off** in the panel or on Today turns it off in that browser. Unticking Read postings automatically in Settings
  turns it off everywhere; the extension then reads nothing, whatever it was told before.
- The extension's options page has a checkbox that stops it in that browser even if jobwatch's setting is on.

## What leaves your computer

Nothing new. The text of a posting and the job's number go from the extension to jobwatch on your own computer, the same
as **Read posting**. There is no analytics, no server of ours, and the extension asks for no new site: it only needs
Chrome's `alarms` (so the pause between two reads survives Chrome putting the extension to sleep) and `idle` (to know
when you are away) permissions.

## Settings

In jobwatch's Settings, Applying tab:

```yaml
autoread:
  enabled: false     # off until you turn it on
  per_day: 25        # a day for each site; 1 to 50, and both sites together never pass 50
  pause_min: 120     # seconds; 60 or more
  pause_max: 180     # seconds; at least 30 more than pause_min
```

A value over a ceiling is refused with a message when you save, not quietly lowered.
