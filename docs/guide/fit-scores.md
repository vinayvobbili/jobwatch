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

Each job is scored once. jobwatch never scores a job again on its own, since every score made again costs
again: after a fallback stood in, after you switch models, or after you edit your resume, the score stays,
saying who made it, until you ask. The local backend takes a minute or two per job, so keep `top` small. On the
page, a tag under each score names the model and where it ran: "Sonnet 5.5 · API", "Sonnet 5.5 · agy",
"Gemini 3.8 Flash · agy", "Qwen3.5-9B · local". A score from an older scorer (your resume or the prompts
changed since) is dimmed and says "old score".

To score a job again, hover its score and press the small ↻ button: a dialog lists the models it can be scored
with (your scoring chain first, then agy's other models, Claude's and this Mac's), with what each costs. The
job is scored in the background with the one you pick, and its new score takes the old one's place on the page
when it's done (the page hears it from jobwatch over Server-Sent Events, `/events`). `jobwatch score --rescore`
does it for many jobs at once.

While `jobwatch ui` runs, it scores every matching job in the background, one at a time: the jobs you've
queued first (they're the ones you're about to apply to), then Today's, most relevant first. It runs when
the page starts, after each "Check for new jobs", when you queue a job, and after you add a new resume. Today shows
how many are left, and a button brings in the new scores when you're ready (the cards don't move on their
own). The local model server queues a chat reply or a "Score fit" click with the background scoring. It's on by default
with `scoring.backend: local`. With `claude` every score is a paid API call, so turn it on with
`scoring.auto: true`. `jobwatch score [--limit N]` does the same in the terminal.

The page is meant to sit close to idle. With nothing left to score it runs no scoring thread. The local model
(several GB) lives in the shared local model server, not in jobwatch: the server loads it when a request comes
and unloads it when idle (`scoring.unload_after` is ignored now). A long line of jobs is scored in batches:
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
model agy uses as a fallback). Without a key, out of credit, out of quota or with the API down, the next
backend scores the job, and a backend that fails moves it on to the one after. The score says so ("fallback",
and which model made it) and stays: it's scored again only when you ask (the ↻ button, or `jobwatch score
--rescore`). `scoring.daily: 40` caps the jobs the page scores with the main backend a day; past it the
fallback scores them (or, with no fallback, they wait for tomorrow). The cap holds back background scoring
only: `jobwatch score` scores what you ask, and counts it. `scoring.per_company: 25` caps the jobs the page
scores from one company a day, so one big board can't fill the line; the company's other jobs say so
("hit today's cap"), wait for tomorrow, and score at once when you press Score fit (0, the default, sets no cap;
Settings has it too). After switching backend or model, `jobwatch score
--rescore 50` scores Today's and queued jobs again, best first, where another model or an older scorer made the
score and it's at least 50.

A fallback entry can name its model, so one backend is tried on another model first. agy keeps a separate
quota per model family, so when its Claude models run out its Gemini ones still answer:

```yaml
scoring:
  backend: agy
  model: claude-sonnet-5-5-medium
  daily: 150                                       # then Flash, keeping Sonnet's quota for other work
  fallback: [agy:gemini-3.8-flash-medium, local]   # agy's Gemini, then this Mac
```

### Any OpenAI-compatible API (a free cloud tier, say)

`scoring.providers` defines an API by name; the name is then a backend in `scoring.fallback` entries (and
`scoring.backend`), always with its model, `name:model`. One block works for any hosted API that speaks the
OpenAI chat-completions protocol (a free cloud tier, Google's Gemini OpenAI-compatible endpoint, Groq):

```yaml
scoring:
  providers:
    acme:
      url: https://api.example.com/v1     # the API's base: jobwatch adds /chat/completions
      keychain: jobwatch-acme             # macOS keychain item with its key (default: jobwatch-<name>)
      # workers: 2                        # calls at once; free tiers allow few
      # response_format: json_schema      # json_object or none, if the API rejects strict schemas
  backend: claude
  fallback: [acme:some-model-id, local]   # the model id as the provider lists it
```

Put the key in the keychain with `security add-generic-password -s jobwatch-acme -a "$USER" -w` (it asks for the
key; `ACME_API_KEY` in the environment works too and is read first). It is sent as `Authorization: Bearer <key>`
and never printed or logged. A 429 or quota error, a 5xx, or a refused key pauses that step (10 minutes for a
5xx, otherwise until its reset or an hour) and the next entry scores; an empty or unreadable answer is a failed
score, not a score. The postings and your resume go to that provider.

To test one on jobs you have already scored, without saving anything:

```
jobwatch score --compare 20 --backend acme --model some-model-id
```

Settings shows such a step in the chain (and keeps it), but adding one is done in the watchlist file.

A score from another backend counts as another model's, even when it's the same model reached another way (agy's
Sonnet and the API's). `scoring.same_as` names the scorers (backend:model) whose scores count as the main
backend's own: `--rescore` leaves their scores alone, and keeps such a fallback, so while agy is out of quota it
redoes Gemini's and the local model's scores through the API instead of waiting:

```yaml
scoring:
  backend: agy
  model: claude-sonnet-5-5-medium
  fallback: [claude:claude-sonnet-5-5, agy:gemini-4-argon-medium, local]
  same_as: claude:claude-sonnet-5-5               # the same Sonnet, through the API
```

A new shortlist-ai (a release, or its prompts or scoring code changed) is another scorer: new jobs are scored
by it, and a job scored before shows its old score as "old score" until you score it again. When the change doesn't
change what a score means (a prompt reordered for caching, say), `jobwatch score --keep-old` keeps the scores
of the scorer in use just before as current instead (`--keep-old ID` names another), so only new jobs are
scored by the new scorer. Scores from scorers replaced before that stay as old scores. If
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
changes scores from then on: new jobs are scored with it, scores made with other prompts show as old scores
until you score them again, and putting the prompts back brings the old scores back. `jobwatch score --show-prompts` prints them.
Editing needs a shortlist-ai that takes edited prompts; with an older one they show read-only.
