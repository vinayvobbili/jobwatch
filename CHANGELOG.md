# Changelog

## Unreleased

- Requires Python 3.11 or newer (3.10 reached end of life in October 2026).
- MCP: `mark_job` with status `applied` asks for proof of submission through elicitation (confirmation page seen,
  confirmation email seen, or not yet) and records nothing on "not yet", decline or cancel; a client without
  elicitation gets the old behaviour plus a warning. `proof_seen=true` skips the question.
