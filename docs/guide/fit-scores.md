# Fit scores

[← jobwatch guide](README.md)

**Tutorial: where the AI runs** (1½ minutes): the Claude API, Antigravity or this Mac; the fallback chain; what
leaves your computer.

https://github.com/user-attachments/assets/40e6f2cb-c201-4da9-ba21-77bdacc464b8

Keyword relevance is fast and explainable, but it can't tell "uses Kubernetes" from "5+ years running
Kubernetes in production". With `resume:` set and `scoring.top` (or `--score N`), the most relevant new
jobs are scored with [shortlist-ai](https://github.com/vinayvobbili/shortlist-ai):

1. It turns the posting into must-have and nice-to-have requirements.
2. It judges each requirement against your resume, with quotes it checks against the resume text.
3. It lists the must-haves the resume doesn't show.

Scores are stored per resume file content, so each job is scored once, and again only after you edit your
resume. The local backend takes a minute or two per job, so keep `top` small. On the page, a tag under each
score says who made it: "Claude API", "local model", or "local, for now" when the local model stood in for
Claude (over `scoring.daily`, or Claude failed) and Claude will score it again.

While `jobwatch ui` runs, it scores every matching job in the background, one at a time: the jobs you've
queued first (they're the ones you're about to apply to), then Today's, most relevant first. It runs when
the page starts, after each "Check for new jobs", when you queue a job, and after you add a new resume. Today shows
how many are left, and a button brings in the new scores when you're ready (the cards don't move on their
own). A chat reply or a "Score fit" click goes first; background scoring waits for it. It's on by default
with `scoring.backend: local`. With `claude` every score is a paid API call, so turn it on with
`scoring.auto: true`. `jobwatch score [--limit N]` does the same in the terminal.

The page is meant to sit close to idle. With nothing left to score it runs no scoring thread and doesn't load
the model; the on-device model (several GB) loads when a job needs it and leaves memory after
`scoring.unload_after` minutes unused (default 5; 0 keeps it loaded). A long line of jobs is scored in batches:
`scoring.batch` jobs in a row (default 10; 0 for no rests), then a rest of `scoring.rest` minutes (default 10)
before the next batch; a new check for jobs or resume starts the next batch at once. `jobwatch service install`
runs the page at a lower priority (nice 10, low-priority disk), so scoring stays out of your way; run it again
to apply that to a service installed earlier.

A job the scorer failed on (no reply, a bad answer) isn't tried again for 3 days, so a down model doesn't make
every pass start with the same failures; that is remembered across restarts, and a change to the resume, the
prompts or the model tries it at once. Its card shows the error.

A card with no score says why: in line to score (and where), no posting text, the same role scored before
this posting came in, or a failure. A job from an alert email may have only its title: "Add the posting"
takes a link to the company's posting (read when it's on a board jobwatch reads) or the pasted text, and so
does `jobwatch mark <key> --url <link>`. `jobwatch unscored` lists them all.

Each score keeps its reasons: every requirement, its verdict (met, partly, missing) and the resume's words
behind it. They're under "Why this score" in a job's details, at the end of `jobwatch show <key>`, and in
the MCP `get_job` result. Scores saved before jobwatch kept these have only the summary.

`filters.min_fit` (the Fit slider on Today's filter bar, and in Settings next to how many picks Today shows)
hides jobs scored below it, counted as "fit" in the hidden roles. Jobs not scored yet still show, since
scoring catches up in the background.

Each score says which model made it (on the ring's tooltip, and in `jobwatch show <key>`). `jobwatch score
--backend claude --model claude-sonnet-5-5` scores with another backend or model for that run only, the
watchlist keeping its own; its scores sit next to the others, so check first that the two grade alike:
`jobwatch score --compare 10 --backend claude` scores 10 already-scored jobs again, from the lowest score to
the highest, and shows each old and new score, the mean difference and which ones land on the other side of
`min_fit`. It saves nothing. With Claude every score is a paid API call.

`scoring.backend: agy` scores with Google's Antigravity CLI (`agy`) on your own subscription login: no API key,
text only, about 35 seconds a call, so up to three run at once. `scoring.model` picks its model (an id from
`agy models`; default `claude-sonnet-5-5-medium`). Each call runs sandboxed in an empty temporary directory, and
it uses your subscription's quota. `agy` can't run the chat, which stays on `claude` or `local`
(`chat.backend`).

To score with Claude and keep other backends for when it can't, set `scoring.fallback: local`, or a list tried
in order, `scoring.fallback: [agy, local]` (Claude, then agy, then the local model; `scoring.agy_model` is the
model agy uses as a fallback). Without a key, out of credit or with the API down, the next backend scores the
job, and a backend that fails moves it on to the one after. The score says so ("fallback", and which backend
made it) and gets scored again by Claude later (after 3 days for a failure), or by `jobwatch score --rescore`. `scoring.daily: 40` caps the jobs the
page scores with Claude a day; past it the fallback scores them (or, with no fallback, they wait for
tomorrow), and Claude takes them up the next day. A fallback score never hides a job from scoring by
`min_fit`. The cap holds back background scoring only: `jobwatch score` scores what you ask, and counts it.
After switching backend or model, `jobwatch score --rescore 50` scores Today's and queued jobs again, best
first, where another model made the score and it's at least 50.

A new shortlist-ai (a release, or its prompts or scoring code changed) is another scorer: its scores start
afresh, and until a job is scored again its old score shows as "old score, rescoring". When the change doesn't
change what a score means (a prompt reordered for caching, say), `jobwatch score --keep-old` keeps the scores
of the scorer in use just before as current instead (`--keep-old ID` names another), so only new jobs are
scored by the new scorer. Scores from scorers replaced before that stay set aside and are scored again. If
the change turns out to move scores after all (`--compare` shows it), `jobwatch score --redo-kept --batch-api`
scores the kept ones again with the new scorer, at half price.

When the model gives no verdict for some of a job's requirements, each would count as not met (a good fit
scoring 5/100), so that run counts as a failure, like an error, and is tried again later. `jobwatch score
--incomplete` scores again the jobs whose saved score is like that, from before.

Claude scores `scoring.workers` jobs at once (4 by default; the on-device model takes one at a time), so
`jobwatch score` goes through a backlog about that many times faster at the same cost. For a big run nobody is
waiting on (a new resume, a backlog, a `--rescore`), `jobwatch score --batch-api` sends it all through Claude's
Message Batches API at half the price. The scoring steps depend on each other, so it goes in rounds of one
batch each (about three); each batch takes minutes, at most a day. Stopping is safe: the next run collects what
was sent instead of paying for it again. A score you ask for on the page (**Score fit**) is wanted now, so it's
never batched.

When nothing is urgent, the page's background scoring can batch too, at half price. Turn on **Half price**
under Settings → Your resume and fit scores (it shows when Claude scores), or in the watchlist:

```yaml
scoring:
  backend: claude
  auto: true
  batch_api: true    # background scores go through the Batches API: half price, in minutes to hours
```

The background scorer then sends as many jobs as Claude may still score today (`scoring.daily`; all of them
without a cap) as one batch, and saves each score when the batch ends. Jobs past the daily limit go to the
fallback as before, one at a time. `jobwatch score` batches by default too. New jobs get their fit a little later
(minutes, at most a day); nothing else changes.

To tighten the prompts for the on-device model without losing paid scores (an edited prompt sets every score
aside), try them in a comparison first: `jobwatch score --compare 20 --stored-by claude --backend local
--prompts tight.yaml` scores 20 of the jobs Claude scored with the local model and the prompts in
tight.yaml (name: text, as `--show-prompts` names them), next to Claude's scores, with the mean size of the
difference to aim down. Nothing is kept, the prompts included: put them in Settings when they're ready.

## The fit score prompt

Settings → **Fit score prompt** shows what the model is told: each of shortlist-ai's prompts (reading the
resume, turning a posting into requirements, judging each requirement, counting years), each in a box you can
edit, with "Reset to default". Only the edited ones are saved, as `scoring.prompts` in the watchlist. The two
request templates must keep their `{placeholders}`; saving says so if one is missing. An edited prompt
changes scores from then on: scores made with other prompts are set aside and Today's jobs are scored again,
and putting the prompts back brings the old scores back. `jobwatch score --show-prompts` prints them.
Editing needs a shortlist-ai that takes edited prompts; with an older one they show read-only.
