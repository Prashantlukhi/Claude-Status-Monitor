# Claude Status Monitor

A floating macOS status panel that shows live **Claude Code session states** — working, waiting for input, done — pinned to your screen edge, always visible while you work.

---

## What It Does

Claude Code hooks write tiny JSON status files to `~/.claude-status/` as Claude works. This panel watches that folder and shows a colored "signal light" for each active session, so you always know what every Claude instance is doing without switching windows.

| Light color | Meaning |
|---|---|
| Orange (pulsing glow) | Claude is working |
| Red (pulsing ring) | Waiting for your input |
| Green | Response complete |
| Grey | Idle / no activity |

---

## Use Cases

**Running multiple Claude sessions at once**
You have 3 projects open — frontend, backend, and a docs task. The panel shows all three lights. You see the backend session turn yellow (needs input) while the others keep working, so you jump in immediately.

**Staying in the zone**
No more alt-tabbing to check if Claude is done. The panel sits at your screen edge; a quick eye glance tells you the status. It even sends a macOS notification + sound when Claude finishes or needs you.

**Multi-monitor setups**
Drag the panel to any display and drop it on the left or right edge. It snaps and remembers. Works correctly on external monitors, including those with negative screen origins (left of the primary).

**Muting low-priority projects**
Right-click a light → Mute. That session's light stays visible but no notifications fire. Good for long background tasks you don't need to babysit.

**IDE + terminal integration**
Left-click a light to jump straight to the project in Cursor / VS Code. Right-click → Open Terminal to open it in your terminal app. Right-click → Copy Path to grab the project path.

**Auto-launch at login**
Run `./monitorctl on` once. The panel comes back automatically on every restart — no need to think about it.

---

## Requirements

- macOS 12 or later
- Python 3.10+
- Claude Code CLI installed and configured

---

## Installation

### 1. Clone the repo

```bash
git clone <repo-url> ~/.claude-status-monitor
cd ~/.claude-status-monitor
```

### 2. Create a virtual environment and install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install pywebview pyobjc
```

`pynput` is optional — only needed if you want a global hotkey to show/hide the panel:

```bash
pip install pynput   # optional
```

### 3. Wire up Claude Code hooks

Add these hooks to your Claude Code settings (`~/.claude/settings.json`):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude-status-monitor/status_writer.py working"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude-status-monitor/status_writer.py working"
          }
        ]
      }
    ],
    "Notification": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude-status-monitor/status_writer.py waiting"
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude-status-monitor/status_writer.py done"
          }
        ]
      }
    ]
  }
}
```

### 4. Start the panel

```bash
./monitorctl start
```

---

## Usage

### monitorctl commands

```bash
./monitorctl start      # Start the panel now
./monitorctl stop       # Close the panel (auto-launch setting unchanged)
./monitorctl restart    # Stop then start
./monitorctl on         # Enable auto-launch at login + start now
./monitorctl off        # Disable auto-launch at login + stop now
./monitorctl status     # Show running state and auto-launch setting
```

### Panel interactions

| Action | Result |
|---|---|
| Hover over panel | Expands to full width |
| Move cursor away | Collapses back to compact |
| Drag the header | Move panel up/down; snaps to nearest screen edge on release |
| Left-click a light | Open that project in your IDE |
| Right-click a light | Menu: Open IDE / Open Terminal / Copy Path / Mute / Dismiss / Force Close |
| Gear icon | Open settings (theme, edge, display, sounds, hotkey, …) |

### Settings

The panel ships with `settings.default.json` as the baseline. Your personal settings are saved to `~/.claude-status-monitor/settings.json` and override the defaults. You can edit either file or use the in-panel gear menu.

Key settings:

| Setting | Default | Description |
|---|---|---|
| `edge` | `right` | Pin to `left` or `right` screen edge |
| `monitor` | `0` | Display index for multi-monitor setups |
| `compact` | `true` | Rest in compact mode, peek full on hover |
| `hover_expand` | `true` | Expand to full width on hover |
| `notify_on_waiting` | `true` | Notify when Claude needs input |
| `notify_on_done` | `false` | Notify when Claude finishes |
| `sound_waiting` | `Submarine` | macOS system sound name |
| `sound_done` | `Glass` | macOS system sound name |
| `hotkey` | `""` | Global hotkey to show/hide (e.g. `<ctrl>+<alt>+m`) |
| `poll_interval` | `0.6` | How often to read status files (seconds) |
| `idle_after` | `120` | Seconds of silence before a "working" IDE session is inferred as waiting |
| `default_ide_app` | `Cursor` | Primary IDE to open projects in |
| `fallback_ide_app` | `Visual Studio Code` | Fallback IDE if primary isn't found |
| `terminal_app` | `Terminal` | Terminal app to open projects in |

---

## How It Works

```
Claude Code hooks
       │
       ▼
status_writer.py   →   ~/.claude-status/<project>.json
                                │
                                ▼
                          monitor.py   →   floating panel (pywebview)
```

- **`status_writer.py`** is called by Claude Code hooks on every tool use, stop, and notification event. It writes a JSON file per session to `~/.claude-status/`. Zero third-party dependencies — intentionally lightweight so it never slows Claude down.
- **`monitor.py`** polls that folder, deduplicates by `session_id`, applies idle-inference for IDE sessions (which don't fire Stop hooks), and pushes updates to the floating WebView panel.
- **`ui/index.html`** is a self-contained HTML/CSS/JS app rendered inside the native macOS window.
- **`monitorctl`** manages the process lifecycle via launchd.

---

## Files

```
.
├── monitor.py              Main panel app
├── monitorctl              Start / stop / auto-launch control script
├── status_writer.py        Hook script — called by Claude Code
├── settings.default.json   Default settings (safe to commit, no personal data)
└── ui/
    └── index.html          Panel UI
```

---

## Troubleshooting

**Panel doesn't appear**
Run `./monitorctl status` to check if it's running. Check `/tmp/claude-monitor.log` for errors.

**No lights showing**
Confirm the hooks are wired up in `~/.claude/settings.json` and that `~/.claude-status/` exists and contains `.json` files after running Claude.

**Lights don't update**
Check that `status_writer.py` is executable: `chmod +x ~/.claude-status-monitor/status_writer.py`.

**Panel flies to wrong position on external monitor**
The panel uses native NSWindow positioning to support negative-origin displays. Make sure `pyobjc` is installed: `pip install pyobjc`.

---

## License

MIT
