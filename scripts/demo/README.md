# Rebuild the demo video

The README's demo video is made from a demo watchlist of made-up companies (Acme, Globex, Initech, Umbrella,
Hooli), made-up jobs and a made-up resume. Nothing in it comes from a real watchlist, and building it never
reaches a job board or calls a model: the jobs are written straight into the demo's state file, and the chat
shows a canned reply.

```
pip install -e '.[dev]' playwright && python -m playwright install chromium
pip install 'slidecast[mlx,yaml,playwright]'    # renders the video; mlx is Kokoro on Apple Silicon
scripts/demo/make-video                          # writes scripts/demo/out/jobwatch-demo.mp4
```

`make-video [OUT] [--music DIR]` runs four steps, each of which also runs on its own:

| Step | Command | Writes (in OUT, default `scripts/demo/out`) |
|---|---|---|
| Seed the demo | `python scripts/demo/seed.py -o OUT/demo` | `demo/`: watchlist, resume, state |
| Screenshot `jobwatch ui` | `python scripts/screenshots.py --demo -c OUT/demo/jobwatch.yaml -o OUT/shots --reply scripts/demo/chat-reply.md` | `shots/*.png` |
| Slides and narration | `python scripts/demo/build.py OUT [--music DIR]` | `slides/*.html`, `reel.yaml` |
| Render | `slidecast render OUT/reel.yaml -o OUT/jobwatch-demo.mp4 --poster` | the video and its poster |

`make-video` also writes `demo.gif`, the README's silent preview. Everything lands in OUT, which git ignores:
commit no screenshots or demo state. To update the README, copy `jobwatch-demo.mp4` and `demo.gif` to `docs/`.

The seed and screenshot steps run in jobwatch's own environment; the render runs in slidecast's. When they're
different installs, point at each: `PYTHON=.venv/bin/python SLIDECAST=/path/to/venv/bin/slidecast
scripts/demo/make-video`, with slidecast's environment activated for the voice (below).

- **The story** (slide order, titles, narration) lives in `slides()` in `build.py`; the chat's answer is
  `chat-reply.md`; the jobs, fit scores and applications are in `seed.py`. Change those, then run
  `make-video` again.
- **The voice** is slidecast's in-process Kokoro (`tts: {provider: mlx, voice: af_heart}`), which needs
  Apple Silicon and a slidecast newer than 0.3.0. For another voice, edit `tts` in `build.py` (slidecast also
  has `kokoro` over HTTP, `say`, `gtts` and `silent`).
  Run it with slidecast's virtualenv activated: on first use the voice installs a spaCy English model
  into it.
- **The music** is a bed and two stings: `music_bed.wav`, `intro_sting.wav` and `outro_sting.wav`.
  `slidecast compose -o DIR` makes them; `build.py` reads them from `--music DIR`, else from OUT. Without
  them the video has the voice only.
- `seed.py` replaces OUT/demo each time, and only ever a folder it made (it leaves a `.jobwatch-demo` mark).
