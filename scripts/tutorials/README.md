# Rebuild the tutorial videos

Seven narrated videos (60 to 120 seconds each: getting started, the daily routine, where the AI runs, applying,
tracking, interview prep, comps and contacts), made like the README demo from made-up data only (Acme, Globex,
Initech...): nothing reads your own watchlist, reaches a job board or calls a model.

```
source .venv/bin/activate          # jobwatch's environment, with playwright and slidecast[mlx,yaml,playwright]
scripts/tutorials/make-tutorials [OUT] [--music DIR]    # OUT defaults to scripts/demo/out (git ignores it)
```

| Step | Command | Writes (in OUT) |
|---|---|---|
| Seed and screenshot the demo | as in `scripts/demo/README.md` | `demo/`, `shots/` |
| Seed the demo with the guide videos' extras (comps, contacts, interviews, a package) | `python scripts/demo/seed.py -o OUT/demo-more --more` | `demo-more/` |
| Screenshot onboarding, Settings and the guide pages | `python scripts/tutorials/shots.py OUT` | `empty/`, `tut-shots/` |
| Slides and narration | `python scripts/tutorials/build.py OUT [--music DIR]` | `tutorials/*/slides`, `reel.yaml` |
| Render | `slidecast render OUT/tutorials/NAME/reel.yaml -o ...` | `tutorials/jobwatch-NAME.mp4` |

The story of each video (slides and narration) is `tutorials()` in `build.py`. The voice and music are the demo's
(see `scripts/demo/README.md`). Copy the finished videos to `docs/tutorials/`.

After uploading them to GitHub and linking them in the README, `python scripts/check_videos.py` downloads every
video the repo page shows and checks each plays to the end and is one of the files in `docs/tutorials/`. The page's
video links expire five minutes after it loads, so a player started later stops after the part it preloaded; that
is GitHub, not the video.
