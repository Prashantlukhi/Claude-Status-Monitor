# Running Claude Code + Gemini CLI + Antigravity in the Same Project

A portable, copy-into-any-project guide for using **Claude Code**, **Gemini CLI**,
and **Antigravity CLI (`agy`)** side by side on one repository — with a single
shared instruction file instead of three drifting copies.

> **Golden rule:** one shared brain (`AGENTS.md`), each tool points at it.
> Never maintain the same instructions in `CLAUDE.md`, `GEMINI.md`, and `AGENTS.md`.

---

## Part A — One-time machine setup (do once per computer)

> ✅ Already completed on this machine (macOS + Homebrew). Listed here so you can
> reproduce it on another machine.

```bash
# 1. Gemini CLI (npm)
npm install -g @google/gemini-cli        # provides:  gemini

# 2. Antigravity CLI (Homebrew cask)
brew install --cask antigravity-cli      # provides:  agy   (NOT `antigravity`)
agy install                              # wires ~/.local/bin into PATH

# 3. Optional: let you type `antigravity` instead of `agy`
echo "alias antigravity='agy'" >> ~/.zshrc

# 4. Reload shell
source ~/.zshrc
```

> ⚠️ **IMPORTANT (as of 2026): Gemini CLI free "Login with Google" is deprecated
> for individuals.** Google sunset the "Gemini Code Assist for individuals" OAuth
> tier. Running `gemini` → Login with Google now fails with:
> *"This client is no longer supported for Gemini Code Assist for individuals…
> please migrate to the Antigravity suite"* — even though the browser says
> "Authentication successful." Consequences:
> - **`agy` (Antigravity) is the supported Google-login path** → use it (see below).
> - The **`gemini` command only works with an API key** now
>   (`selectedType: "gemini-api-key"` + a key from https://aistudio.google.com/apikey).
>   There is no working free OAuth path for the `gemini` command anymore.

### Authenticate (interactive — you must run these yourself)

```bash
gemini        # first run: choose "Login with Google"; use your Gemini Pro account
agy           # first run: prompts for Google sign-in
```

- Use your **Gemini Pro** Google account at the Gemini login for the higher limits.
- Auth is a browser flow, so it can't be scripted — run it once, then it's cached.

### Switch auth: remove API key → use Google login (Gemini CLI)

Gemini CLI stores *which* auth method to use in `~/.gemini/settings.json`
(`security.auth.selectedType`), not the key itself. Switching is a preference change.

**Easiest (in-app):** start a session and run the `/auth` command:
```bash
gemini
```
```text
/auth              # opens the auth picker
                   # → choose "Login with Google"  (starts the browser OAuth flow)
```

**Or edit the setting directly**, then relaunch:
```jsonc
// ~/.gemini/settings.json
{
  "security": {
    "auth": {
      "selectedType": "oauth-personal"   // was: "gemini-api-key"
    }
  }
}
```
- `oauth-personal` = Login with Google · `gemini-api-key` = API key · `vertex-ai` = Vertex.
- Also delete any key you exported earlier so it can't override the login:
  ```bash
  unset GEMINI_API_KEY GOOGLE_API_KEY
  # and remove any matching `export ...` line from ~/.zshrc / ~/.zprofile
  ```
- Verify after logging in: run `gemini`, then `/stats` (shows quota) and check that
  `~/.gemini/oauth_creds.json` now exists.

### Log in with a different / additional Google account

The active account is tracked in `~/.gemini/google_accounts.json`; the login token
is cached in `~/.gemini/oauth_creds.json`.

```bash
# 1. Log out (clears the cached Google token)
rm -f ~/.gemini/oauth_creds.json

# 2. Log back in — the browser will let you pick a different account
gemini            # → /auth → "Login with Google" → choose the other account
```
- If the browser auto-uses the wrong account, sign out at
  https://accounts.google.com or use its account switcher, then retry.
- To confirm which account is active afterward:
  ```bash
  cat ~/.gemini/google_accounts.json
  ```

### Antigravity (`agy`) — the supported Google-login CLI

`agy` has **no `login` subcommand** — it authenticates automatically on first
interactive launch:
```bash
agy          # (or: antigravity) → browser Google sign-in → use your Gemini Pro account
```
It caches the session under `~/.gemini/antigravity-cli/`. To switch/add a different
Google account, clear that folder and run `agy` again to re-trigger the login:
```bash
rm -rf ~/.gemini/antigravity-cli/<auth-cache>   # inspect the folder first
agy
```

### Verify the machine is ready

```bash
gemini --version      # e.g. 0.54.x
agy --version         # e.g. 1.1.x
which gemini agy      # both should resolve
```

> ⚠️ **Command names:** the Antigravity CLI binary is **`agy`**, not `antigravity`.
> The `antigravity` alias above just makes the longer word work too.
> (`antigravity`, `antigravity-ide`, and `antigravity-cli` are *three different*
> Homebrew casks — the desktop app, the IDE, and this terminal CLI respectively.)

---

## Part B — Per-project setup (run in EACH existing project)

Do this inside a project that already has Claude Code set up. It is **additive** —
it does not touch your existing `.claude/` folder.

### Step 1 — Create the shared `AGENTS.md`

This holds knowledge **every** agent should have. Move the generic parts of your
current `CLAUDE.md` here (architecture, conventions, testing, guardrails).

```md
# Project Instructions

## Architecture
<!-- stack, structure, key modules -->

## Coding Rules
- Reuse existing components before creating new abstractions.
- Run the test suite before considering a task complete.
- Match the surrounding code's style and naming.

## Guardrails
- Never commit secrets. Do not modify `.env` files.
- No schema changes without a migration.
- Explain large architectural changes before making them.
```

### Step 2 — Point Gemini CLI at the shared file

Gemini's default context file is `GEMINI.md`. Tell it to read `AGENTS.md` too.
Create **`.gemini/settings.json`** in the project root:

```json
{
  "context": {
    "fileName": ["AGENTS.md", "GEMINI.md"]
  }
}
```

> Older Gemini CLI versions used a flat top-level key instead:
> `{ "contextFileName": ["AGENTS.md", "GEMINI.md"] }`.
> If the nested form isn't picked up, try the flat one. Confirm with `/memory show`
> inside a `gemini` session — it prints which context files were loaded.

### Step 3 — Make `CLAUDE.md` thin (import the shared file)

Claude Code supports `@path` imports. Reduce `CLAUDE.md` to a Claude-specific entry
point that pulls in the shared brain:

```md
# Claude Code Instructions

@AGENTS.md

## Claude-specific
- Use the skills, subagents, and hooks in `.claude/`.
- Delegate independent tasks to appropriate subagents.
```

### Step 4 — (Optional) Antigravity context

The `agy` CLI is agentic like Claude Code. It conventionally reads `AGENTS.md`, but
its help doesn't document context files, so **verify empirically**: run `agy` in the
project and ask "what project instructions did you load?" before relying on it.
If it ignores `AGENTS.md`, keep using it for read-only review tasks where project
context matters less.

### What stays Claude-specific (do NOT copy into `AGENTS.md`)

| Keep in `.claude/` | Reason |
|---|---|
| `.claude/skills/` | Claude skill format; may use Claude-only tools |
| `.claude/agents/`  | Claude subagent mechanism |
| `.claude/hooks/`   | Claude hook system |
| `.claude/settings*.json` | Claude permissions/config |

Only the **generic knowledge** inside those (e.g. "review DB migrations: check
history, verify backwards-compat") is portable — lift that into `AGENTS.md` if you
want other tools to know it too.

### Resulting layout

```text
my-project/
├── AGENTS.md              ← shared brain (all agents)
├── CLAUDE.md              ← thin, @imports AGENTS.md
├── .claude/               ← untouched: skills / agents / hooks / settings
├── .gemini/
│   └── settings.json      ← contextFileName → AGENTS.md
├── GEMINI.md              ← optional, Gemini-only notes
└── src/ ...
```

---

## Part C — Command cheat sheet

### Gemini CLI

```bash
gemini                      # interactive session in current dir
gemini -p "review auth.ts for bugs; don't edit anything"   # one-shot, print & exit
```
Inside a session (slash commands):
```text
/memory show               # show which context files (AGENTS.md/GEMINI.md) loaded
/skills                    # list available agent skills
/mcp                       # manage MCP servers
/help                      # all commands
```

### Antigravity CLI (`agy`, aliased `antigravity`)

```bash
agy                        # interactive agent session
agy -c                     # continue most recent conversation
agy -p "summarize recent changes"   # one-shot print mode
agy --mode plan            # start in plan mode (no edits)
agy --model <name>         # pick model
agy agents                 # list available agents
agy --dangerously-skip-permissions   # auto-approve tools (use with care)
```

### Claude Code

```bash
claude                     # your existing workflow, unchanged
```

---

## Part D — Working with all three safely

Treat each agent like a **separate developer on the same desk** — they can clobber
each other's edits if they touch the same files at once.

**Before switching tools, checkpoint:**
```bash
git status && git diff
git add -A && git commit -m "checkpoint before switching agents"
```

**For bigger tasks, isolate with branches or worktrees:**
```bash
git worktree add ../proj-gemini -b gemini-review
# run gemini in ../proj-gemini, claude in the main tree — no collisions
```

**A workflow that plays to each tool's strengths:**
```text
claude   → implement the feature
  ↓ commit
gemini   → independent second-opinion review ("find bugs/edge cases, don't edit")
  ↓ fix
claude   → verify changes match conventions + run tests
```

---

## Part E — Auth, usage & config: Claude Code vs Gemini CLI vs Antigravity

All three are agentic terminal CLIs with slash commands, but their auth models,
usage metering, and config layouts differ. Slash commands below are run **inside**
a session; see `/help` in each tool for the live, complete list.

### E.1 — Auth: log in / log out / switch account or key

| Action | Claude Code | Gemini CLI (`gemini`) | Antigravity (`agy`) |
|---|---|---|---|
| Log in | `/login` | `/auth` → pick method → browser | relaunch `agy` (first run auto-prompts) |
| Log out | `/logout` | *no logout command* — use `/auth`, or delete `~/.gemini/oauth_creds.json` | **`/logout`** (disconnects profile, purges tokens from keyring) |
| Switch account | `/login` (re-auth) | `rm ~/.gemini/oauth_creds.json` then `/auth` → choose account | `/logout` then relaunch `agy` → sign in with other account |
| Change auth **method** | n/a (account only) | **`/auth`** → API key / Google / Vertex AI | n/a — Google-account only |
| Change API **key value** | n/a | edit `GEMINI_API_KEY` env var or `~/.gemini/settings.json`, or re-run `/auth` | n/a |

> **Reminder (2026):** Gemini CLI's free Google-login is deprecated for individuals
> (see Part A warning). In practice: `gemini` → API key, `agy` → Google login.

### E.2 — Check usage / limits / quota (the `/status` equivalent)

| | Claude Code | Gemini CLI | Antigravity (`agy`) |
|---|---|---|---|
| Session usage | `/status`, `/cost` | **`/stats`** — duration, tool calls, tokens | in status line + `/usage` |
| Quota / limits | `/status` (plan usage) | **`/stats model`** — token counts + quota | **`/usage`** (alias `/quota`) — model quota |
| Credits / billing | `/cost` (API $) | Cloud Console / AI Studio for API billing | **`/credits`** — remaining G1 credits + top-up |
| Raise limits | upgrade plan | **`/upgrade`** (Google-login only) | buy G1 credits (`/credits`) |

> Antigravity and a Gemini API key are **separate quota pools** — usage on one does
> not draw down the other (see the quota note earlier in this doc).

### E.3 — Config files & locations

| Concern | Claude Code | Gemini CLI | Antigravity (`agy`) |
|---|---|---|---|
| User (global) config | `~/.claude/settings.json` | `~/.gemini/settings.json` | `~/.gemini/antigravity-cli/settings.json` |
| Project config | `.claude/settings.json` (+`.local`) | `.gemini/settings.json` | per-project trust in `trustedWorkspaces` |
| Context / instructions | `CLAUDE.md` (+`@imports`) | `GEMINI.md` (configurable → `AGENTS.md`) | `AGENTS.md` (agentic, Claude-Code-style) |
| Skills | `.claude/skills/` | `/skills` (Agent Skills) | `builtin/skills/` + user skills |
| Subagents | `.claude/agents/` | extensions | `agy agents` / `--agent` |
| Hooks | `.claude/hooks/` | settings hooks | see `agy` docs (`agy-customizations`) |
| MCP servers | `.mcp.json` / settings | `gemini mcp ...` | plugins / MCP config |
| Memory store | conversation + CLAUDE.md | `/memory` (GEMINI.md hierarchy) | `brain/` + `knowledge/` dirs |

### E.4 — Model selection

| | Command |
|---|---|
| Claude Code | `/model` (or `--model`) |
| Gemini CLI | `/model set <name>` / `/model manage`; flag `--model` |
| Antigravity | `/model` (persists across sessions); `agy models` lists them; flag `--model` |

`agy` exposes multiple families — e.g. `gemini-3.x-pro/flash`, `claude-*`,
`gpt-oss-*`. List them anytime with `agy models`.

### E.5 — Key `agy` settings.json keys (`~/.gemini/antigravity-cli/settings.json`)

```jsonc
{
  "colorScheme": "…",          // visual theme (dark/light variants)
  "toolPermission": "request-review", // request-review | proceed-in-sandbox | always-proceed | strict
  "enableTerminalSandbox": false,     // restrict agent commands to OS containment
  "enableTelemetry": false,
  "notifications": true,
  "editor": "…",               // editor for prompt composition
  "verbosity": "…",            // output detail level
  "statusLine": { "enabled": true, "type": "", "command": "" }, // custom status line (like Claude's)
  "trustedWorkspaces": ["/path/to/project"], // folders agy is allowed to act in
  "useG1Credits": false         // spend personal credits once plan quota is exhausted (external builds)
}
```
Edit interactively inside a session with **`/config`** (alias `/settings`).

### E.6 — Conceptual differences to keep in mind

- **Auth model:** Claude = Anthropic account/API key · Gemini = Google account **or**
  API key (individual OAuth deprecated) · Antigravity = Google account (+ G1 credits).
- **Billing:** Claude subscription/API · Gemini API key = per-token (or AI Studio
  free tier) · Antigravity = plan quota then optional G1 credits.
- **`agy` is closely modeled on Claude Code** — same ideas: plan/accept-edits modes
  (`--mode`), `--continue`, `--dangerously-skip-permissions`, skills, subagents,
  MCP, hooks, a status line. If you know Claude Code, `agy` will feel familiar.
- **Permissions:** Claude `.claude/settings.json` allow-lists vs `agy`
  `toolPermission` levels vs Gemini's per-tool approval + `--yolo`/sandbox.

---

## Part F — Wiring Gemini CLI and Antigravity (`agy`) into the Claude Status Monitor

`~/.claude-status-monitor` (see its own `README.md`) only ever watched
`~/.claude-status/*.json` — it's tool-agnostic by design. Originally only Claude
Code's hooks (`~/.claude/settings.json`) wrote to that folder, so Gemini CLI and
`agy` sessions never showed a signal even though the panel itself didn't care who
wrote the file. Fixed by wiring each tool's own hook system to the same
`status_writer.py`, and teaching `status_writer.py` to read either tool's payload
shape. Both use their own event names and (for `agy`) a different JSON shape than
Claude Code, so this isn't a copy-paste of the Claude Code hook block.

### Gemini CLI — `~/.gemini/settings.json` → `"hooks"`

Gemini CLI hooks live in `settings.json` (see the CLI's own bundled
`docs/hooks/reference.md`), and its base input schema already sends
`{cwd, session_id, hook_event_name, tool_name, ...}` — the same field names
Claude Code uses — so `status_writer.py` reads it unmodified. Wired events:

| Gemini event | → status |
|---|---|
| `SessionStart` (matcher `startup`) | `idle` |
| `BeforeAgent` | `working` (Gemini's analogue of Claude's `UserPromptSubmit`) |
| `BeforeTool` / `AfterTool` | `working` |
| `Notification` (tool-permission alerts) | `waiting --label approval` |
| `AfterAgent` (Gemini's analogue of Claude's `Stop`) | `done` |
| `SessionEnd` | `end` |

> ⚠️ Verified the hook config loads and is schema-valid, but couldn't confirm it
> *fires* live on this machine — `gemini`'s free "Login with Google" is broken
> for individuals (see Part A), so real turns fail before any hook would run.
> Needs a `GEMINI_API_KEY` (or the Antigravity suite) to confirm end-to-end.

### Antigravity (`agy`) — `~/.gemini/config/hooks.json`

`agy` hooks live in a **separate `hooks.json` file**, not `settings.json` —
checked at `.agents/hooks.json` per-workspace, or `~/.gemini/config/hooks.json`
globally (all 3 "flavours" of Antigravity read the same locations). Confirmed
this by watching `~/.gemini/antigravity-cli/log/cli-*.log` for
`hooks_manager.go` load/parse lines while iterating on the file.

**Schema pitfall:** the schema differs by event. `PreToolUse`/`PostToolUse` nest
like Claude Code's (`matcher` + `hooks: [{type, command}]`), but
`PreInvocation`/`PostInvocation`/`Stop` are a **flat array** of `{type, command}`
directly — no `matcher`, no `hooks` wrapper. Getting this wrong doesn't error
loudly; it logs `invalid hook "<name>": command hook must specify 'command'` to
the CLI log and silently no-ops. Wired events:

| `agy` event | → status |
|---|---|
| `PreToolUse` / `PostToolUse` (matcher `*`) | `working` |
| `PreInvocation` | `working` (fires before each model call, i.e. new turn) |
| `Stop` | `done` |

`agy`'s payload has **no `cwd`/`session_id`/`tool_name`** — instead
`workspacePaths: [...]`, `conversationId`, `toolCall: {name, ...}`.
`status_writer.py` now falls back to these when the Claude/Gemini-style fields
are absent, so one script serves all three tools.

**Verification note:** `agy -p` (headless/print mode) is known-flaky in non-TTY
contexts (see `google-antigravity/antigravity-cli` issues #318, #76) and did
**not** reliably fire hooks when scripted here. Confirmed the wiring actually
works by watching a real, already-running interactive `agy` session's status
file update live in `~/.claude-status/` — don't re-test with `agy -p` and
conclude it's broken.

### Files touched

- `status_writer.py` — payload field normalization (`cwd`/`session_id`/`tool_name`
  now fall back to `agy`'s `workspacePaths`/`conversationId`/`toolCall.name`).
- `~/.gemini/settings.json` — added `"hooks"` block (Gemini CLI).
- `~/.gemini/config/hooks.json` — new file (Antigravity `agy`).

---

## Quick per-project checklist

- [ ] `AGENTS.md` created with the generic project rules
- [ ] `.gemini/settings.json` points `contextFileName` at `AGENTS.md`
- [ ] `CLAUDE.md` slimmed to `@AGENTS.md` + Claude-specific notes
- [ ] `gemini` → `/memory show` confirms `AGENTS.md` is loaded
- [ ] `.claude/` left untouched
- [ ] Committed a checkpoint before running a second agent
