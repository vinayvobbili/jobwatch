# Prep sheets

[← jobwatch guide](README.md)

**Tutorial: interview prep** (2 minutes): prep sheets, answers drafted from your stories, a mock interview, a
drill video, finding a story.

https://github.com/user-attachments/assets/c8ac1030-700f-4cdd-823d-4b92cd411bf3

Before a recruiter call or an interview, open the application's **Details** and press **Prep sheet** (or run
`jobwatch prep c1`). One page, ready to print, with:
- the stage, next step and your notes;
- each requirement and responsibility in the posting, next to the line on your resume closest to it (the
  resume you sent, if you kept it), or a plain "nothing close" so you can prepare a story or an honest answer;
- skills they ask for that your resume doesn't show, with the fit score's missing must-haves;
- a company brief: what the posting says about the company in its own words, its place and team, your notes
  on the job and who you know there. It's drawn from the posting and your notes only (nothing is looked up
  on the web) and says so;
- pay: the posted range, your target (`pay.target`, a number or a range) and your floor (`pay.floor`), with how each sits against the
  range. The floor is marked private: it is on your own sheet and nowhere else (see below);
- what you sent;
- questions to expect and questions to ask, for a screen or for interviews.

**Questions for this role.** `jobwatch prep c1 --questions` (or **Write questions for this role** on the page)
has the chat's model write the questions this role is likely to bring up from the posting's asks, each probing
one of them. Only the posting goes to the model (no resume, no stories, nothing of yours), and a question with a
number the posting doesn't contain is dropped. They're kept per job and posting text, so opening the sheet again
doesn't call the model, and a changed posting asks afresh. With no model, or nothing usable, the generic screen
or interview questions stand and the sheet says why. `prep.role_questions(cfg, store, key)` returns them for
anything else that wants them (such as a mock interview).

**Your pay floor stays on your computer.** Set `pay.target` and `pay.floor` (a yearly base, in the posting's
currency) in the watchlist; the target may be a range (`target: 180000-210000`, or `target_max: 210000`), and
the sheet says whether it sits below, inside, across or above the posted range. The sheet shows the floor labelled private. It is never put in a prompt for Claude:
with `chat.backend: claude` the posted range and your target may go in the questions prompt, the floor is left
out, and the sheet says so. The on-device model may see it. `get_interview_prep` over MCP leaves it out too
(`pay.floor_withheld`), since the client may be a cloud assistant.

**Open as page** (or `jobwatch prep c1 --open`) shows it as a standalone HTML page that prints cleanly on Letter
paper; `--format html -o prep.html` saves that page, and the default `--format md` prints Markdown.

Nothing on it is written for you: it quotes the posting and your resume. For an application you added by hand,
jobwatch looks for the posting on your watched boards by the requisition id in its title (`R0123456`,
`REQ-4711`, `Job 20769`), so a Workday posting fetched later fills in the sheet.

## Drafted answers from your stories

`jobwatch prep c1 --draft` adds the one part that is written for you, and only from what you've written
yourself: 6 to 10 questions this role is likely to bring up, each with the requirement it probes, and an
answer outline built from your stories and your resume, naming the stories it used. A question none of them
answers says "no story yet", with one honest line: what's closest, and how you'd ramp up.

Your stories are a YAML file you write once and point the watchlist at (`stories: ~/Documents/stories.yaml`).
Each is a project you'd talk about on a call:

```yaml
- id: alert-dedupe                    # what answers cite it by
  title: Cut duplicate on-call alerts
  did: Built a Python service that groups alerts about the same incident before they page anyone.
  hard: The teams named the same hosts three different ways.
  result: Pages per week went from 120 to 35 in two months.
  skills: [Python, Kafka]             # optional
  avoid: [the vendor's name]          # optional: details you're not sure of, or don't want said
```

[examples/stories.yaml](../../examples/stories.yaml) has a few more, made up. You don't have to write them by hand:
[Find a story](#find-a-story) interviews you and adds one for you. After editing it by hand, `jobwatch stories`
checks it and lists what's there. A mistake in the file (a missing
`result`, two stories with the same id) is reported with the story and what to fix.

The model is told never to invent experience, numbers, employers or credentials, and its answer is checked
anyway before it reaches the sheet:
- an answer citing a story you don't have is dropped;
- a point with a number that's in neither the stories it cites nor your resume is dropped (a number is what
  you'd repeat word for word, so it isn't just flagged);
- a point that says one of a story's `avoid` details is dropped too;
- an answer left with no story becomes "no story yet";
- it's cut to length, and a reply that isn't the JSON asked for gives no drafts.
The sheet says what was taken out. With no model, an error or nothing usable, it keeps the usual questions:
prep never fails because the model did.

It uses the chat's model (`chat.backend`): `local` keeps everything on your computer; with `claude` the
posting, your resume and your stories go to Anthropic. A draft takes a while, so it's kept in the state file
and opening the sheet again reads it; a change to the posting, resume, stories, stage, model or instructions
drafts afresh. Its instructions are `drafts.PROMPT`, or your own in `prep.prompt` (keep `{context}`, where the
posting, resume and stories go); `prep.max_tokens` (4000) is the longest draft. MCP clients ask for it with
`get_interview_prep`'s `draft_answers`, and for role questions `role_questions`; the sheet it returns has
`brief`, `pay` and `role_questions` as fields of their own.

## Mock interview

`jobwatch ask --job c1 --mock` (or **Mock interview** at the top of the prep sheet in `jobwatch ui`) practises
the call one question at a time. The questions come from the prep sheet: one for each requirement and
responsibility in the posting first, then the usual ones for the stage (and the drafted ones, when you've
drafted them). Type your answer, or `skip`, `repeat` or `quit`; a summary closes the session.

Each answer gets short feedback from the chat's model: what landed, what's missing against the posting's asks,
and a tightened version. The model is told to use only facts from your answer, your stories and your resume,
never to invent experience, numbers, employers or tools, and to write "[add a real example of X]" where
something is missing. The code checks the numbers too: a tightened answer with one that's in none of those isn't
offered, and neither is one that says a story's `avoid` detail you didn't say yourself. Saving it is your call (`y/N`, or **Save to the prep sheet**): saved answers are kept with the job's
package, one per question, and show on its prep sheet under **Practised answers**, and in MCP's
`get_interview_prep` as `practised`. It runs on the chat's backend like the rest (`local` stays on your
computer; with `claude` the posting, your resume and your stories go to Anthropic); with none available it says
what to install, before asking anything.

## Drill video

`jobwatch prep c1 --drill drill.mp4` turns the prep sheet into a video to rehearse with. Each question is asked in
one voice, then the screen says **Answer out loud** and holds for 75 seconds (`--pause 60` to change it), then
a second voice reads the answer while its full text is on screen, a page at a time for a long one, so you can
read along as you hear it. `--no-pause` drops the hold, for a quick review.

The answers are only ones the sheet already has: practised answers from mock interviews, then drafted outlines
told with the stories they cite (so run `--draft` first, or practise with `--mock`). A question with no answer is
left out, never filled in. The key can also be a prep sheet you wrote yourself, as HTML: every table with a
"Question" column and an "Answer" column gives one question a row, and so does every question heading
(`<h3 class="q">`) with a "say" block under it (`<div class="say">`), its paragraphs read as one answer. Text in
`class="muted"` (sources, asides) isn't spoken, nor is a paragraph with a `class="fill"` blank you haven't filled
in, nor a follow-up line like `If they push: "…"`:

```
jobwatch prep ~/prep/acme-sheet.html --drill ~/prep/acme-drill.mp4 --no-pause
```

It needs `pip install 'jobwatch[video]'`, which brings [slidecast](https://pypi.org/project/slidecast/) with
Kokoro voices that run on your Mac (Apple Silicon), and a browser to draw the slides (Chrome, or slidecast's
Playwright extra). Nothing is sent anywhere. The first run fetches the voice model and a small English language
model once.

## Find a story

A prep sheet shows where you're thin: an ask with nothing close on your resume, a drafted question with "no story
yet". Often there is a story; you just haven't remembered it. **Find a story** (at the top of the prep sheet, or
beside any of those lines) has the chat's model interview you about one of them, and writes what you tell it up
as a story for your story file. From the command line: `jobwatch ask --job c1 --story` lists the gaps to pick
from, or name your own (`jobwatch ask --job c1 --story "running a migration"`).

It asks one question at a time, starting broad: have you done anything like it, even partly, as a participant,
long ago? When you don't remember the details, it may offer what usually happens in a case like yours, under
**Common patterns, not your case**, for you to confirm or not. It's told never to present one as what you did,
to keep your real role (taking part isn't leading, a prototype isn't production), and to leave out what's
unsafe to say aloud: internal system names, people's names, the country of the people involved. With nothing
close, it says so and suggests one honest line instead.

When it has what you did, the hard part and how it ended (or you press **Write it up**), it proposes the story.
The code checks it before you see it: one with a number you never typed isn't offered, and neither is one that
says a detail it listed under `avoid`. You then check every line in the card, edit any of it, and press **Save
to my stories** (`y` on the command line). Nothing is saved before that. It's added to the end of your story file
with comments and the rest left as they were (the old file is kept as `.bak`); with no `stories:` set, it starts
`stories.yaml` beside the watchlist and names it there. Drafted answers and mock interviews use it from then on.

It runs on the chat's backend like the rest: `local` stays on your computer; with `claude` the posting, your
resume, your stories and what you type go to Anthropic. An assistant connected over MCP can run the same
interview itself: `get_interview_prep` returns `story_gaps`, and `save_story` keeps what you confirm.
