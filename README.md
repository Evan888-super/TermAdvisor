# TermAdvisor

Suggestions-only terminal advisor. When a command fails, or when you ask, it explains the failure and prints copy-pasteable fixes. It never runs those fixes for you.

There is no GUI. Cards are printed in the terminal you already use.

Default model host is [Nebius Token Factory](https://tokenfactory.nebius.com/) with `nvidia/nemotron-3-super-120b-a12b`. Any OpenAI-compatible endpoint works. Web search, if you turn it on, uses [Tavily](https://tavily.com/).

## Features

- **Local first.** Typos, missing commands, a busy port, and a missing pip/npm module are answered on your machine. Those cards say `local` and do not call an API.
- **Model cards.** Harder failures go to Nemotron Super (or another OpenAI-compatible model). Those cards say `model`.
- **Shell hook.** Optional bash, zsh, or fish snippet records the last command, exit code, and folder. Watch mode can print a card after a failure. It does not run the suggestion.
- **Ignore list.** The hook skips TermAdvisor itself, `__systemd_osc_context*`, `ls`, `cd`, and `pwd`. Successful commands are not stored (`failures_only`).
- **Redaction.** Tokens, passwords, and private-key blocks are stripped before a network call. Config file mode is `0600`.
- **Advice cache.** The same command, exit code, and log tail within 30 minutes returns `cache` and does not call the model again.
- **Optional log capture.** Off by default. `wrap` or a pipe already captures a log. `capture on` plus `script` lets the hook see terminal output.
- **Optional Tavily search.** Off until you store a key and set `search=on`. Used only when the local router misses. Source files are not sent to Tavily.

## What it will not do

- It will not run `npm install`, `sudo`, or `rm` for you.
- It will not explain a successful command unless you pass `--model-only` or use `ask`.
- It will not see the red error text from the hook unless you `wrap`, pipe a log, pass `--file`, or turn capture on inside `script`.

## Requirements

- Linux, macOS, or Windows with WSL
- Python 3.11+
- `typer`, `rich`, and `openai` (`openai` is only needed for model calls)
- A Nebius (or other) API key for model cards
- A Tavily key only if you want web search

## Install

From this repository:

```bash
cd ~/TermAdvisor
python3 -m pip install --user typer rich openai
```

Fastest run, no install step. Point `PYTHONPATH` at this tree and alias the command. If an older checkout exists, do not leave both on `PYTHONPATH`.

```bash
echo 'export PYTHONPATH="$HOME/TermAdvisor/src${PYTHONPATH:+:$PYTHONPATH}"' >> ~/.bashrc
echo 'alias TermAdvisor="python3 -m termadvisor"' >> ~/.bashrc
source ~/.bashrc
```

Editable install, if you want a real `TermAdvisor` binary in `~/.local/bin`:

```bash
cd ~/TermAdvisor
python3 -m pip install --user -e .
export PATH="$HOME/.local/bin:$PATH"
```

Check that the command is this tree:

```bash
type TermAdvisor
TermAdvisor version
TermAdvisor --help
```

`--help` should list `tavily-login`, `search`, and `capture`. If it does not, the alias is still pointing at another checkout.

## First run

No key needed:

```bash
TermAdvisor demo
printf 'bash: gitt: command not found\n' | TermAdvisor explain --offline --no-interact --command 'gitt status' --exit 127
```

The second card should say `local` and suggest `git status`.

Model key, stored in `~/.config/TermAdvisor/config.toml` (mode `0600`), not in the repo:

```bash
TermAdvisor login
```

Or `export NEBIUS_API_KEY=...` and skip storing it. `TermAdvisor status` prints `key present` and never the raw key.

Optional hook:

```bash
TermAdvisor init --shell bash
source ~/.bashrc
TermAdvisor on    # automatic card after a failure
TermAdvisor off   # record only; explain still works
```

## Commands

| Command | What it does |
|---|---|
| `TermAdvisor explain` | Explain the last recorded failure, a pipe, or `--file` |
| `TermAdvisor ask "question"` | Ask about the last failure. Skips the local router |
| `TermAdvisor wrap -- cmd args` | Run a command, keep its log, advise if it fails |
| `TermAdvisor last` | Show the last stored command and exit code |
| `TermAdvisor demo` | Canned card, no network |
| `TermAdvisor login` | Store the model key |
| `TermAdvisor tavily-login` | Store the Tavily key. Search stays off |
| `TermAdvisor search "query"` | Tavily only. Does not call the model |
| `TermAdvisor capture on` | Allow the hook to read a `script` session log |
| `TermAdvisor init` | Install the shell hook |
| `TermAdvisor on` / `off` | Watch mode |
| `TermAdvisor status` | Watch, model, keys, cache, search |
| `TermAdvisor config show` | Settings with keys masked |
| `TermAdvisor config set key=value` | Change one setting |

Useful flags on `explain`:

- `--offline` — local rules only
- `--model-only` — skip the local router
- `--search` — attach Tavily snippets before the model call
- `--no-cache` — do not read or write the advice cache
- `--no-interact` — print the card and exit
- `--file build.log` — use a log file
- `--command` / `--exit` — override what the hook stored

After a card, `[c]` copies suggestion 1, a number copies that suggestion, `[e]` prints detail, `[n]` dismisses. Nothing is executed.

## Search

Tavily is off until both of these are true:

```bash
TermAdvisor tavily-login
TermAdvisor config set search=on
TermAdvisor status
```

`status` should show `tavily search on` and `tavily key yes`.

Docs only:

```bash
TermAdvisor search "yt-dlp error no such option"
```

Search, then Super:

```bash
printf 'yt-dlp: error: no such option: --fake-flag\n' \
  | TermAdvisor explain --no-interact --search --no-cache \
      --command 'yt-dlp --fake-flag URL' --exit 2
```

Detail should mention that Tavily snippets were attached. A typo such as `yt-dfp` stays `local` and does not search.

## Capture

Leave capture off for normal use. The hook stores command, exit, and folder only.

One command, with its log:

```bash
TermAdvisor wrap --offline --no-interact -- gitt status
```

Session log, only while you are inside `script`:

```bash
TermAdvisor capture on
script -q -f ~/.cache/TermAdvisor/session.log
# fail a command here, then
exit
TermAdvisor explain --no-interact
```

`script` records the session. The next model call can send that tail. Turn capture off when you are done: `TermAdvisor capture off`.

## Config

File: `~/.config/TermAdvisor/config.toml`

| Setting | Default | Meaning |
|---|---|---|
| `watch` | off | Card after a failed command |
| `model` | `super` | `super`, `nano`, `ultra`, or a full model id |
| `redact` | on | Strip secrets before the network |
| `local_first` | on | Try local rules first |
| `failures_only` | on | Do not store exit 0 |
| `ignore` | see file | Hook skip list, comma-separated when set from the CLI |
| `capture_output` | off | Read `session.log` in the hook |
| `cache_advice` | on | Reuse a recent model card |
| `cache_ttl_s` | 1800 | Cache lifetime |
| `search` | off | Tavily before the model |
| `upload_source_snippets` | on | Send nearby source lines to the model, not to Tavily |

```bash
TermAdvisor config set watch=off
TermAdvisor config set model=nano
TermAdvisor config set upload_source_snippets=false
TermAdvisor config set search=off
```

## Privacy

Local cards never leave the machine. A `model` card sends the command, exit code, folder, redacted log tail, and optional source snippets to the model host. A Tavily call sends the redacted command and last error line, not your source files.

Nebius can see the prompt and the completion it generates. Their docs say content is not used to train the main models. Unless you enable Zero Data Retention on the Nebius account, inputs and outputs may be stored for speculative decoding. That switch is in their dashboard, not in TermAdvisor.

The API keys live in `~/.config/TermAdvisor/config.toml` or in `NEBIUS_API_KEY` / `TAVILY_API_KEY`. Publishing this repo does not publish those keys, as long as `config.toml` is not committed.

## Tests

```bash
cd ~/TermAdvisor
python3 -m pip install --user pytest
PYTHONPATH=src python3 -m pytest -q
```

## Troubleshooting

**`No such command 'tavily-login'`**

The alias is running an old checkout. `type TermAdvisor` and `echo $PYTHONPATH` must point at the tree whose `--help` lists `tavily-login`. Update `PYTHONPATH` to `$HOME/TermAdvisor/src` and `source ~/.bashrc`.

**`No module named pytest` / `typer` / `rich` / `openai`**

Those are not in the standard library.

```bash
python3 -m pip install --user typer rich openai pytest
```

**`explain` talks about an old command**

It uses the last stored failure. Override it:

```bash
TermAdvisor explain --command 'npm run build' --exit 2 --file build.log
```

**`explain` says the last command succeeded**

Exit code was 0. That is intentional. Use `ask` if you still want commentary.

**Card says Offline mode**

You passed `--offline`, or no local rule matched and the model was not called. Drop `--offline` after `login`.

**Card says local for a typo**

Expected. `--model-only` forces Super. Tavily is not used on a local hit.

**Model error, 401, or model not found**

`TermAdvisor status` should show `key present yes`. Re-run `TermAdvisor login`. NVIDIA NIM uses a different base URL:

```bash
TermAdvisor login --base-url https://integrate.api.nvidia.com/v1
TermAdvisor config set api_key_env=NVIDIA_API_KEY
```

**Tavily 401 or empty search**

`TermAdvisor tavily-login`, then `TermAdvisor config set search=on`. `TermAdvisor search "yt-dlp"` should print snippets before you involve Super.

**Hook records TermAdvisor or `__systemd_osc_context_precmdline`**

Reinstall the snippet after updating `hook.py`:

```bash
TermAdvisor init --shell bash
source ~/.bashrc
```

**`[1]+ Done python3 -m termadvisor __hook`**

Job-control noise from an old hook. `TermAdvisor init --shell bash` replaces the block with one that `disown`s the helper.

**Capture on, but explain has no log**

You did not run the failure inside `script -q -f ~/.cache/TermAdvisor/session.log`. Use `wrap` instead.

**Git pull says divergent branches**

Your machine and GitHub each have commits the other lacks. Inspect `git status` and `git log`, then `git pull --no-rebase origin main`. Do not `git reset --hard` unless those local commits are disposable.
