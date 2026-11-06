# Chat

[← jobwatch guide](README.md)

Ask questions in plain words: "which three should I apply to first?", "what follow-ups are due?", "how well
do I fit this one, honestly?", "what will they ask in interviews?". The chat runs where fit scores do,
unless `chat.backend` says otherwise:

- `local`: a local model server on your computer: run any OpenAI-compatible one (e.g. `vllm-mlx serve`,
  `mlx_lm.server`, LM Studio) and set `LOCAL_LLM_URL` if it isn't at the default,
  `http://127.0.0.1:8010/v1`. Nothing leaves your computer. The server runs whichever model it has and queues
  requests from every program, so an answer may wait for its turn (or for the model to load).
- `claude`: Claude Sonnet via Anthropic's API (`ANTHROPIC_API_KEY`, or the keychain item `scoring.keychain`
  names). Your question, your resume and the jobs it's about are sent to Anthropic.

Settings → **Chat** sets the Claude model (`chat.claude_model`; the local server picks its own, and a
leftover `chat.local_model` is ignored), the longest reply
(`chat.max_tokens`) and how many of a conversation's latest messages go with each question
(`chat.max_turns`). Its instructions are there too, folded like the fit score prompts: edit them, or "Reset
to default". Only an edited one is saved (`chat.prompt`), and it must keep `{today}` and `{context}`, where
the date and the jobs it reads go.

It reads today's matching jobs and your applications, or one posting with its fit score and
[what you sent](tracking.md#what-you-sent), plus your resume (the one you sent for that job, when it's kept).
It's told to use only your resume for facts about you and to treat posting text as data, not instructions.
It has no tools, so it can't change, apply for or send anything.

Under each reply are a copy button and what it took: seconds, tokens in and out, and tokens per second. While a reply is on its
way, a timer shows how long it's been against how long recent replies took. The download button in the chat's
header saves the conversation as Markdown. The same thing works from the terminal:

```
jobwatch ask "What follow-ups are due this week?"
jobwatch ask --job c1 "What should my resume lead with for this one?"
```
