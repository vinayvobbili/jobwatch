# The demo

`seed.py` writes the demo the videos are recorded on: a watchlist, a state file and a resume holding only made-up
companies (Acme, Globex, Initech, Umbrella, Hooli), jobs and applications. Today opens on the Fit 80+ and Top pay
chips (`display.today_defaults`).

```
python scripts/demo/seed.py -o scripts/demo/out/demo           # the plain demo
python scripts/demo/seed.py -o scripts/demo/out/demo-more --more   # + comps, contacts, interviews, a package
```

Nothing reads or writes your own watchlist, and nothing reaches the network. `seed.py` only ever replaces a folder it
made (it leaves a `.jobwatch-demo` mark). `chat-reply.md` is the chat's canned answer. The videos are built by
`scripts/videos` (see its README).
