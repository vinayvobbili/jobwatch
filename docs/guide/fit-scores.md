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
"Gemini 3.8 Flash · agy", "Qwen3.5-9B · local". A score made under an older resume keeps showing, with a small
amber clock on its ring ([more below](#a-new-resume-and-the-scores-you-already-have)).

To score a job again, hover its score and press the small ↻ button: a dialog lists the models it can be scored
with (your scoring chain first, then agy's other models, Claude's and this Mac's), with what each costs. The
job is scored in the background with the one you pick, and its new score takes the old one's place on the page
when it's done (the page hears it from jobwatch over Server-Sent Events, `/events`). `jobwatch score --rescore`
does it for many jobs at once.

While `jobwatch ui` runs, it scores every matching job in the background, one at a time: the jobs you've
queued first (they're the ones you're about to apply to), then Today's, most relevant first. It runs when
the page starts, after each "Check for new jobs", when you queue a job, and after you add a new resume. Today shows
how many are left, and a button brings in the new scores when you're ready (the cards don't move on their
own). The local model server queues a chat reply or a "Score" click with the background scoring. It's on by default
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

Why an alert job has no text: the email carries a title, company and place (sometimes pay), and LinkedIn and
Indeed show a posting only to a signed-in browser, so jobwatch can't fetch it. `jobwatch fill-text` fills what
it can without you: from the company's own board, then the job's own link. For a LinkedIn or Indeed link, the
card says so and has a **Read posting** button: it opens the job in a new tab of your own browser and the
jobwatch extension copies the posting's text to jobwatch and closes the tab (you must be signed in there). With
the newest extension the tab opens behind this one and only the card changes; with an older one the tab opens in
front, and jobwatch says once to update or reload the extension.
`jobwatch fill-text --open` lists those links, and `jobwatch fill-text --set KEY --page-text FILE` saves the text
of a page you or an assistant read in the browser (the description is cut out of the page; a sign-in wall or a
captcha is refused).

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

### Which local model to run

`scoring.backend: local` talks to any OpenAI-compatible server at `http://127.0.0.1:8010/v1` (or `LOCAL_LLM_URL`):
`vllm-mlx serve`, `mlx_lm.server`, LM Studio, or Ollama (at `http://127.0.0.1:11434/v1`, with `scoring.model`
set to the tag). The page's "On this Mac" card (Settings › Where the AI runs, and onboarding) reads this
computer's memory and suggests one from this table, with the command that serves it. Only the 16 GB row was
tested; the others are suggested, sized by memory.

| Memory | Mac with Apple Silicon (MLX, runs on the GPU via Metal) | Windows, Linux or Intel Mac (Ollama) | Also good: Gemma 4 (MLX first, then Ollama) |
|---|---|---|---|
| 8 GB | Qwen3.5-4B, 4-bit: [`Qwen3.5-4B-MLX-4bit`](https://huggingface.co/mlx-community/Qwen3.5-4B-MLX-4bit) | [`qwen3.5:4b-q4_K_M`](https://ollama.com/library/qwen3.5:4b-q4_K_M) | E2B: [`gemma-4-e2b-it-4bit`](https://huggingface.co/mlx-community/gemma-4-e2b-it-4bit); [`gemma4:e2b-it-q4_K_M`](https://ollama.com/library/gemma4:e2b-it-q4_K_M) |
| 16 GB (tested) | Qwen3.5-9B, 4-bit: [`Qwen3.5-9B-MLX-4bit`](https://huggingface.co/mlx-community/Qwen3.5-9B-MLX-4bit) | [`qwen3.5:9b-q4_K_M`](https://ollama.com/library/qwen3.5:9b-q4_K_M) | 12B, tested: most accurate (29/29 vs 28/29), about 50% slower, +1.7 GB: [`gemma-4-12B-it-4bit`](https://huggingface.co/mlx-community/gemma-4-12B-it-4bit); [`gemma4:12b-it-q4_K_M`](https://ollama.com/library/gemma4:12b-it-q4_K_M) |
| 24-32 GB | Qwen3.8-27B, 4-bit: [`Qwen3.8-27B-4bit`](https://huggingface.co/mlx-community/Qwen3.8-27B-4bit) | [`qwen3.8:27b-q4_K_M`](https://ollama.com/library/qwen3.8:27b-q4_K_M) | 26B-A4B: [`gemma-4-26b-a4b-it-4bit`](https://huggingface.co/mlx-community/gemma-4-26b-a4b-it-4bit); [`gemma4:26b-a4b-it-q4_K_M`](https://ollama.com/library/gemma4:26b-a4b-it-q4_K_M) |
| 48 GB and up | Qwen3.6-35B-A3B, 4-bit: [`Qwen3.6-35B-A3B-4bit`](https://huggingface.co/mlx-community/Qwen3.6-35B-A3B-4bit); 8-bit with 64 GB or more: [`Qwen3.6-35B-A3B-8bit`](https://huggingface.co/mlx-community/Qwen3.6-35B-A3B-8bit) | [`qwen3.6:35b-a3b-q4_K_M`](https://ollama.com/library/qwen3.6:35b-a3b-q4_K_M); 8-bit: [`qwen3.6:35b-a3b-q8_0`](https://ollama.com/library/qwen3.6:35b-a3b-q8_0) | 31B: [`gemma-4-31b-it-4bit`](https://huggingface.co/mlx-community/gemma-4-31b-it-4bit); [`gemma4:31b-it-q4_K_M`](https://ollama.com/library/gemma4:31b-it-q4_K_M) |

On computers with 48 GB or more, 35B-A3B-style models (about 3B active parameters) are the fastest choice.

On an Apple Silicon Mac, use MLX: it's built for Apple's chips and runs faster than Ollama there. Ollama is for
computers MLX doesn't run on.

On Apple Silicon, serve a row with `vllm-mlx serve mlx-community/<repo> --port 8010`; elsewhere,
`ollama pull <tag>`. That is the same command for a Gemma 4 repo: vllm-mlx recognizes a gemma-4 name, loads it
through mlx-vlm (which it installs) and serves it text and all on the same port. The 8 GB row's Gemma is E2B, not
E4B, because E4B's 5.2 GB of weights would crowd an 8 GB computer. The 16 GB row was compared on a 16 GB Apple Silicon Mac against a 6-bit build of the same
model and Gemma 4 12B (4-bit) on 29 expected requirement verdicts: 28, 27 and 29 agreed, at 27, 36 and 42
seconds a call and 7.5, 9.7 and 9.2 GB. The gap was within noise, so the faster and smaller 4-bit Qwen stays the suggestion, and Gemma 4 12B
(the most accurate, about 50% slower, 1.7 GB more) is the "also good" for that row.
The page only notes when a model you already set is larger than the suggestion for your memory.

To score with Claude and keep other backends for when it can't, set `scoring.fallback: local`, or a list tried
in order, `scoring.fallback: [agy, local]` (Claude, then agy, then the local model; `scoring.agy_model` is the
model agy uses as a fallback). Without a key, out of credit, out of quota or with the API down, the next
backend scores the job, and a backend that fails moves it on to the one after. The score says so ("fallback",
and which model made it) and stays: it's scored again only when you ask (the ↻ button, or `jobwatch score
--rescore`). `scoring.daily: 40` caps the jobs the page scores with the main backend a day; past it the
fallback scores them (or, with no fallback, they wait for tomorrow). The cap holds back background scoring
only: `jobwatch score` scores what you ask, and counts it. `scoring.per_company: 25` caps the jobs the page
scores from one company a day, so one big board can't fill the line; the company's other jobs say so
("hit today's cap"), wait for tomorrow, and score at once when you press Score (0, the default, sets no cap;
Settings has it too). After switching backend or model, `jobwatch score
--rescore 50` scores Today's and queued jobs again, best first, where another model made the score (or you marked
it stale, below) and it's at least 50.

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
      # account_url: https://example.com/account   # shown as an "Account" link on the provider's card in Settings
  backend: claude
  fallback: [acme:some-model-id, local]   # the model id as the provider lists it
```

Put the key in the keychain with `security add-generic-password -s jobwatch-acme -a "$USER" -w` (it asks for the
key; `ACME_API_KEY` in the environment works too and is read first). It is sent as `Authorization: Bearer <key>`
and never printed or logged. A 429 or quota error, a 5xx, or a refused key pauses that step (10 minutes for a
5xx, otherwise until its reset or an hour) and the next entry scores; an empty or unreadable answer is a failed
score, not a score. The postings and your resume go to that provider.

`jobwatch scorers` lists each step of the chain, active or paused (until when, why, and whether a run or you set
it), without a page or a model call. Hold a step you know is out, such as agy's Sonnet until its weekly reset, so
no batch of jobs fails against it first: `jobwatch scorers --pause agy:claude-sonnet-5-5-high --until "2026-12-01
22:00" --reason "weekly quota"` (your local time); the chain skips it like one a run found out of quota.
`jobwatch scorers --resume STEP` ends the pause.

A run pauses a whole quota pool, not one step, since the steps on one account run out together: `claude_api`
(Claude's API, also paused by the credit's daily cap until midnight Eastern and by its total cap until you resume
it), `agy_claude_gpt` (agy's Claude and GPT models), `agy_gemini` (agy's Gemini models), `local`, and a provider's
own. `jobwatch scorers` lists them first as flags (available: yes, or no and back at when, and why), Settings shows
them as green or amber dots, and `--pause --pool agy_gemini --until ...` or `--resume --pool agy_gemini` hold or
free one by hand. A pause ends on the clock at the time the error named (an hour when it named none), even across a
restart; a step that scores clears its pool's pause.

To test one on jobs you have already scored, without saving anything:

```
jobwatch score --compare 20 --backend acme --model some-model-id
```

Or set it up in Settings, with no file editing and no shell: **Settings → AI & fit scores → Cloud providers**.
Pick a preset (OpenRouter, Groq, Google AI Studio, or Custom for any other OpenAI-compatible API) to fill in the base URL, name it, paste the key
(it goes to the macOS keychain item `jobwatch-<name>` and is never shown again), pick a model from the list the API
gives (or type its id), press **Test** (OK, auth failed or rate limited), then **Add to chain** and Save. The step
appears in the chain above, where ← → reorder it. **Remove** takes the provider out of the watchlist and leaves
its keychain item alone. Without a macOS keychain, the card says to set `ACME_API_KEY` (for a provider named
`acme`) before starting jobwatch.

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

**An API credit that ends.** To spend a promotional credit on scoring and then go back to the free scorers, give the
Claude entry its last day: `claude:claude-sonnet-5-5 until 2026-12-20`. A dated entry scores first, ahead of
`scoring.backend`, until that day in New York time (the credit's own clock); on that day and after it is skipped,
with one line in the Activity log ("credit window ended"), and the chain is the free scorers again. While it runs,
a ledger adds up what its calls cost at list price (from the tokens the API reports; the prices are in
`scorestats.PRICES`, and a model with no price isn't used) and stops it at a daily cap for the rest of that day
(`scoring.credit.daily_usd`, 3) and a total cap for good (`scoring.credit.total_usd`, 90). The caps are checked
every 5 jobs, so a run can pass one by a few cents. An account that refuses it (no credit, a key refused, a rate
limit) is skipped for an hour without a retry storm, the jobs go to the next scorer, and none is marked failed.
Its scores aren't marked as a fallback, so list it in `same_as` to have `--rescore` leave them alone.

```yaml
scoring:
  backend: agy
  fallback: ["claude:claude-sonnet-5-5 until 2026-12-20", agy:gemini-4-argon-medium, local]
  same_as: claude:claude-sonnet-5-5
  credit: {daily_usd: 3, total_usd: 90}           # these are the defaults
```

`jobwatch credit` shows the entry, what the ledger has spent against the caps and whether it would score now;
`jobwatch credit --test` scores the one unscored job with the shortest posting through it alone (nothing else is
tried), to see one charge arrive in the Anthropic Console before turning it on. `--entry 'claude:MODEL until
YYYY-MM-DD'` tests an entry that isn't in the watchlist. The key comes from `scoring.keychain` like any Claude call.

A new shortlist-ai (a release, or its prompts or scoring code changed) is another scorer: new jobs are scored
by it, and the scores made before keep showing, unflagged: a new scorer never marks a score stale by itself
(`jobwatch scores` counts how many another version made). If the change turns out to move scores after all
(`--compare` shows it), mark them stale (below) or, for the ones `jobwatch score --keep-old` kept from the
scorer before, `jobwatch score --redo-kept --batch-api` scores them again with the new scorer, at half price.

## A new resume and the scores you already have

A rebuilt resume doesn't change a score, hide one or ask for a new one. Every job keeps the score it has, and
the page shows it with a small amber clock on the ring's rim (never over the number) when it was made under an older
resume (hover it: "scored under an older resume"). Stale scores count like any other: the Fit filters (60+, 70+, 80+) and Best fit
order use them, the card's advice reads them, and "No score yet" is only for jobs that never had one. Nothing is
scored again until you decide what the change means, once you have judged how much it matters:

- Today says "12 scores predate your resume" (Settings → AI & fit scores → Scores and your resume has the same
  note). **Decide…** opens a dialog: **Keep scores** makes the current resume the baseline (the badges go, nothing is
  scored, nothing is paid); **Mark stale** puts the scores you pick (every score, those at your Fit minimum or 60+,
  the queued jobs', or both of those) in line to be scored again, with a reason for the log.
- The same from the shell: `jobwatch scores` says how many scores were made under which resume;
  `jobwatch scores --keep --reason "fixed a typo"`; `jobwatch scores --stale --min 60 --queued --reason "new
  summary"` (`--min` and `--queued` together pick either); `jobwatch scores --unmark` takes marks back;
  `jobwatch scores --log` lists the decisions.
- A marked score shows a rose clock ("marked stale on 2026-11-26: new summary") until the job is scored
  again, by the page's background scoring when `scoring.auto` is on, the Score button, `jobwatch score --rescore`
  (best first) or `--batch-api`. Each new score replaces it.
- Keeping is per resume: the next rebuild flags the scores again. Putting an old resume back makes the scores made
  under it current again.

Which resume made each score is kept with it (the resume's name and a short fingerprint of its text), so nothing is
lost either way: both decisions only change what the page flags and what is scored next.

When the model gives no verdict for some of a job's requirements, each would count as not met (a good fit
scoring 5/100), so that run counts as a failure, like an error, and is tried again later. `jobwatch score
--incomplete` scores again the jobs whose saved score is like that, from before.

Claude scores `scoring.workers` jobs at once (4 by default; the on-device model takes one at a time), so
`jobwatch score` goes through a backlog about that many times faster at the same cost. For a big run nobody is
waiting on (a new resume, a backlog, a `--rescore`), `jobwatch score --batch-api` sends it all through Claude's
Message Batches API at half the price. The scoring steps depend on each other, so it goes in rounds of one
batch each (about three); each batch takes minutes, at most a day. Stopping is safe: the next run collects what
was sent instead of paying for it again. A score you ask for on the page (**Score**) is wanted now, so it's
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
changes scores from then on: new jobs are scored with it, and scores made with other prompts show as stale,
as for a new resume (decide as above), and putting the prompts back makes them current again. `jobwatch score --show-prompts` prints them.
Editing needs a shortlist-ai that takes edited prompts; with an older one they show read-only.
