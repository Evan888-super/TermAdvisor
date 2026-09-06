# TermAdvisor

**A suggestions-only terminal agent.** When a command fails — or when you ask — it reads the error output and explains what went wrong. It does not run commands on your machine.

Powered by [NVIDIA Nemotron 3 Super](https://developer.nvidia.com/topics/ai/nemotron) through an OpenAI-compatible API such as [Nebius Token Factory](https://tokenfactory.nebius.com/).

---

## What it does

You keep using the terminal as usual. TermAdvisor sits in the background (or waits until you call it), sends the failed command plus the last lines of output to Nemotron Super, and prints a short diagnosis with copy-pasteable fixes.

```text
$ npm run build
src/api.ts:41: error TS2345: Argument of type 'string' is not assignable to ...

────────────────────────────────────────
TermAdvisor  ·  exit 2  ·  2.1s
Cause: parseId() returns string; UserId expects a number.
Try:
  1. Number(parseId(req.params.id))
  2. Widen UserId to string (API-wide; riskier)

[c] copy 1   [e] more detail   [n] dismiss
────────────────────────────────────────
```

It is a **reader and advisor**, not an operator. You type every command yourself.

---

## What it is not

- Not a website you paste logs into (that can exist later as a demo)
- Not an agent that auto-runs `npm install`, `sudo`, or `rm`
- Not a local install of the 120B model — Super stays on the API host
- Not a web-search product — no Tavily or other search key is required

Terminal knowledge (shells, compilers, package managers, common stack traces) is already in the model. Your log supplies the missing piece: *this* failure, *this* project.

---

## How it works

```text
your shell
   │  command + exit code + tail of stdout/stderr
   ▼
TermAdvisor (local)
   │  redact secrets
   │  optionally read a few lines of files named in the stack
   ▼
Nebius Token Factory (or any OpenAI-compatible endpoint)
   │  NVIDIA Nemotron 3 Super 120B-A12B
   ▼
suggestion card in the terminal
```

1. A small local program captures the command, working directory, exit code, and a trimmed log tail.
2. Secrets that look like tokens, passwords, or PEM blocks are stripped **before** the network call.
3. That bundle is sent to Nemotron Super.
4. The model returns a short cause plus suggested commands.
5. You copy or ignore them. Nothing is executed unless *you* paste and run it.

Login happens once. After that you only toggle watching on or off.

---

## Requirements

- macOS, Linux, or Windows with WSL
- Python 3.11+
- A network connection when advice is generated
- An API key for Nemotron Super, for example a **Nebius Token Factory** key (`NEBIUS_API_KEY`)

You do **not** need GPUs, Tavily, or a second search vendor.

---

## Install

```bash
pip install TermAdvisor
# later: brew install TermAdvisor
```

---

## Quick start

```bash
TermAdvisor login          # paste the API key once
TermAdvisor init           # hook bash / zsh / fish
# open a new terminal
```

Work as usual. When a command exits non-zero and watching is on, a card appears.

```bash
TermAdvisor off            # silence
TermAdvisor on             # watch failed commands again
TermAdvisor status         # on/off, model, key present?
```

The key is stored in `~/.config/TermAdvisor/config.toml` (file mode `0600`). You do not log in every session.

---

## Usage

### On demand (always available)

```bash
TermAdvisor explain              # last command / last failure
cat build.log | TermAdvisor explain
TermAdvisor ask "why is port 3000 in use?"
```

On-demand mode is the safest default: no API call until you ask.

### Automatic on error (optional)

```bash
TermAdvisor on
```

After this, a **failed** command can trigger one suggestion card. Successful commands stay silent. Turn it off with `TermAdvisor off`.

Recommended defaults:

| Event | Behavior |
|---|---|
| Command succeeds | Do nothing |
| Command fails, watching **off** | Do nothing until `explain` |
| Command fails, watching **on** | Show a suggestion card |
| You type `explain` / pipe a log | Advise even if watching is off |

---

## Configuration

```bash
TermAdvisor config set watch=off          # never auto-fire
TermAdvisor config set model=super        # or nano for cheaper / faster
TermAdvisor config set max_tail_lines=2000
```

Example `~/.config/TermAdvisor/config.toml`:

```toml
[provider]
base_url = "https://api.tokenfactory.nebius.com/v1/"
api_key_env = "NEBIUS_API_KEY"
model = "nvidia/nemotron-3-super-120b-a12b"

[behavior]
watch = false          # on-demand only until you opt in
max_tail_lines = 2000
redact = true

[privacy]
upload_source_snippets = true   # few lines around path:line in the stack
```

Point `base_url` at any OpenAI-compatible host (Nebius Token Factory, NVIDIA NIM, OpenRouter, a self-hosted vLLM box).

---

## Safety

TermAdvisor **v1 is suggestions-only**:

- It never runs shell commands for you
- It never requests `sudo`
- It redacts common secret patterns before they leave the machine
- It sends a **tail** of the failed output, not the entire day’s scrollback
- High-risk suggestions (delete, force-push, cluster destroy) are labeled so you can ignore them

You still decide what to paste into the prompt. Do not treat advice as authoritative on production systems.

A later, optional `apply=confirm` mode could run a command *after you type `y`*. That is not the default and is not required for the product to work.

---

## Privacy

What may be sent to the model provider when you ask for advice (or when auto-watch fires):

- The command string
- Exit code and working directory
- The last N lines of output
- Optionally a small source window around `file:line` in a stack trace

What should not be sent:

- Full `.env` files
- Unredacted tokens
- Your entire terminal history

The provider is whoever owns the endpoint in `base_url` (for example Nebius). Read their retention policy. Prefer a zero-retention endpoint if you handle customer or production logs.

---

## Architecture (for builders)

The interesting part is not the model call. The model call is one OpenAI-style `chat.completions` request. The product is the wrapper:

```text
TermAdvisor/
  src/TermAdvisor/
    cli.py        # login, init, on, off, explain, ask, status
    hook.py       # bash / zsh / fish snippets
    capture.py    # last command, exit, tail
    redact.py     # secrets
    context.py    # snippets from stack-trace paths
    provider.py   # OpenAI-compatible client
    render.py     # suggestion card
    config.py
```

Suggested implementation language for v1: **Python 3.11+** (`typer`, `openai`, `rich`).

Shell hooks stay in bash/zsh/fish. A paste-a-log website, if you add one, should hit the same explain function — not a second brain.

---

## Roadmap

- [x] Design: suggestions-only CLI, login once, on/off
- [ ] `explain` from stdin / last command
- [ ] Secret redaction
- [ ] Shell hooks + `on` / `off`
- [ ] Optional source snippets from `path:line`
- [ ] Cheap-model router for trivial errors (`command not found`)
- [ ] Optional confirm-to-run (not default)
- [ ] Optional web/CI paste UI using the same API

---

## FAQ

**Do I need Tavily or another search API?**  
No. Super already knows common terminal and compiler patterns. Search is an optional later tool for brand-new packages or post-cutoff docs.

**Does it execute fixes?**  
Not in v1. It only suggests. You run what you trust.

**Does advice appear automatically?**  
Only if you turn watching on. Otherwise it waits for `explain` / `ask`.

**Must I start a GUI every day?**  
No. Login once. Then `on` / `off`. There is no separate app window.

**Can I use Ultra instead of Super?**  
Yes, if the endpoint offers it. Super is the intended default: strong enough for logs and stack traces, cheaper than Ultra. Nano is enough for one-line errors.

**Is this RAG?**  
Not unless you also index READMEs or old errors. Sending the current log is long-context reading. Adding retrieval over your repo or past failures would make it RAG.

---

## License

To be chosen when the repo is published (recommended: MIT or Apache-2.0 for the client; Nemotron weights and API use remain under NVIDIA’s and the host’s terms).

---

## Name

Working name: **TermAdvisor**. Replace freely. The product is the loop: *failed command → redacted log → Nemotron Super → suggestion card.*
