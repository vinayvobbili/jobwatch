# Rebuild the videos

The 1.5-minute tour (`docs/jobwatch-demo.mp4`) and the seven tutorials (`docs/tutorials/jobwatch-0N-*.mp4`) are screen
recordings of the real `jobwatch ui` and of the Chrome extension's side panel, on made-up data (Acme, Globex, Initech,
Umbrella, Hooli): nothing reads your own watchlist, reaches a job board or calls a model. They show the UI, with a
visible cursor, a ripple on every click and nothing cut off at the frame's edges. The only commands on screen are the
uv-first install: install uv, `uv tool install jobwatch`, `jobwatch ui`.

```
source .venv/bin/activate            # jobwatch's environment, with playwright and slidecast[mlx,yaml,playwright]
python -m playwright install chromium
scripts/videos/make-videos --dry     # a screenshot after each action, to check framing (cheap, no video)
scripts/videos/make-videos           # record and render every video (Kokoro narration; needs Apple Silicon)
scripts/videos/make-videos jobwatch-demo jobwatch-04-applying    # just those
python scripts/videos/publish.py     # copy them into docs/ and site/, with posters and the tour's demo.gif
```

Output goes to `scripts/demo/out/videos/NAME/` (git ignores it): `clips/`, `NAME.mp4`, its poster, and for the tour a
1440p `jobwatch-demo-youtube.mp4`. Music: `slidecast compose -o scripts/demo/out` writes the bed and stings that
`build.py` reads by default.

| File | What it holds |
|---|---|
| `stories.py` | The tour, every scene's narration and mouse actions (`Scene`), the page helpers |
| `tutorials.py` | The seven tutorials |
| `extension.py` | The extension's side panel docked beside a form or LinkedIn list |
| `cards.py` | The title card (silent 3 s, and the closing card), the animated problem scene |
| `common.py` | The seeded demo, `Scene` and `Video`, the narration timing |
| `build.py` | Records the scenes, assembles the reel, renders it, writes its captions |
| `captions.py` | `NAME.vtt` from the narration and the rendered segments' lengths; run alone it captions videos already rendered, with no re-render (`python scripts/videos/captions.py`, then `publish.py --captions-only`) |

The story follows slidecast's shape: a silent title card, the problem, the tagline "Your job hunt shouldn't be a
full-time job." at the turn, the walkthrough, and the title card again. Each clip is held as long as its narration.
slidecast's `Recorder` moves the cursor and fails a scene when a sticky or fixed element is sliced by the frame's edge;
`slidecast check` on each finished video checks the ends. The demo is `scripts/demo/seed.py` (`--more` adds comps,
contacts, interviews and a saved package); the chat's canned reply is `scripts/demo/chat-reply.md`.

Keep demo figures invented: never a real pay figure, employer or place.
