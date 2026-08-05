#!/usr/bin/env python3
"""
monitor.py  --  floating "signal tower" panel, Stage-Manager style.

Pins to a screen edge (left/right), rests compact, peeks to full on hover,
slides vertically by dragging, remembers its position, and supports picking a
display on multi-monitor setups.

  Hover the panel        -> peeks to full size (when resting compact)
  Leave it               -> returns to resting mode
  Drag the header        -> moves it up/down; snaps to the nearest edge
  Left-click a light      -> opens that project's IDE
  Right-click a light     -> menu (open IDE / terminal / copy path / mute / dismiss)
  Gear                   -> settings (edge, display, sounds, colors, ...)

Dependencies:  pip3 install pywebview pyobjc   (pynput optional, only for a hotkey)
"""

import os
import sys
import json
import time
import glob
import shutil
import threading
import subprocess
from urllib.parse import urlparse, unquote

import webview  # pip3 install pywebview

# pyobjc — used to position the native window directly in global screen
# coordinates (see _place_topleft). Optional: we fall back to pywebview's
# move() if it isn't importable for some reason.
try:
    from PyObjCTools import AppHelper
except Exception:
    AppHelper = None

# NSEvent.mouseLocation() lets us detect hover from the cursor's GLOBAL position,
# which works even when the panel isn't the focused window (see hover_watch).
try:
    from AppKit import NSEvent
except Exception:
    NSEvent = None

# By default macOS swallows the first click on a non-focused window just to
# activate it -- so a click on our background panel's header never reaches the web
# content to start a drag (you'd have to click once to focus, then again to drag).
# Overriding acceptsFirstMouse: on WKWebView to return True delivers that first
# click straight to the content, so the header is grabbable in one motion even when
# another app is focused. A category patches the live class, affecting every
# instance pywebview creates regardless of when it's created.
try:
    import objc
    from WebKit import WKWebView

    class WKWebView(objc.Category(WKWebView)):
        def acceptsFirstMouse_(self, event):
            return True
except Exception:
    pass

HOME = os.path.expanduser("~")
APP_DIR = os.path.join(HOME, ".claude-status-monitor")
STATUS_DIR = os.path.expanduser(os.environ.get("CLAUDE_STATUS_DIR", "~/.claude-status"))
UI_FILE = os.path.join(APP_DIR, "ui", "index.html")
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
DEFAULTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.default.json")

DEFAULT_SETTINGS = {
    "theme": "dark",
    "accent": "#6E8BFF",
    "opacity": 0.92,
    "show_icon": True,
    "compact": True,          # resting mode: True = rest compact, peek full on hover
    "hover_expand": True,     # peek to full on hover
    "edge": "right",          # right | left
    "monitor": 0,             # display index for multi-monitor
    "pos_y": None,            # remembered vertical offset within the chosen display
    "width_full": 260,
    "width_compact": 92,
    "edge_margin": 8,
    "top_margin": 36,
    "font_scale": 1.0,
    "default_ide_app": "Cursor",
    "fallback_ide_app": "Visual Studio Code",
    "terminal_app": "Terminal",
    "notify_on_waiting": True,
    "notify_on_done": False,
    "sound_waiting": "Submarine",
    "sound_done": "Glass",
    "hotkey": "",             # empty = no global hotkey (no Input Monitoring prompt)
    "poll_interval": 0.6,
    "remember_position": True,
    "sort": "urgency",
    "muted": [],
    "idle_after": 120,         # seconds a "working" session may go quiet before
                              # we infer it's waiting (covers IDE sessions, whose
                              # Stop/Notification hooks never fire; 0 disables).
                              # Kept high to avoid false positives during extended
                              # thinking phases between tool calls.
}

STATUS_RANK = {"waiting": 0, "working": 1, "idle": 2, "done": 3}


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    for src in (DEFAULTS_FILE, SETTINGS_FILE):
        try:
            if os.path.exists(src):
                with open(src) as f:
                    s.update({k: v for k, v in json.load(f).items() if k in DEFAULT_SETTINGS})
        except Exception:
            pass
    return s


class App:
    def __init__(self):
        self.settings = load_settings()
        self.window = None
        self.api = Api(self)
        self._stop = False
        self._prev_status = {}
        self.peeking = False
        self._hover_inside = False   # last known cursor-inside-window state (hover_watch)
        self._last_h = 200
        self._last_pos = (0, 0)     # latest absolute window position from 'moved'
        self.dragging = False       # true while the user is holding/dragging
        self._hotkey_listener = None
        self.active_idx = int(self.settings.get("monitor", 0) or 0)
        # session_ids for which we have observed a proper Stop/Notification hook
        # firing (status was written as "waiting", "done", or "idle" by the hook).
        # Once a session is in this set we never apply idle_after inference to it,
        # eliminating false "waiting for input" signals during thinking phases.
        self._sessions_with_hooks: set = set()

    # ---------- geometry ----------
    # We position the NATIVE NSWindow directly in global screen coordinates.
    # pywebview's own window.move() anchors to NSScreen.mainScreen() (the focused
    # display, NOT necessarily the primary), so on a multi-monitor setup where a
    # secondary display sits to the left (negative origin) it offsets every move
    # and flings the panel off-screen. Talking to the native window avoids that:
    # our coordinates are absolute, so the panel lands correctly on any display.
    #
    # Our internal convention everywhere below: (global_x, py) where global_x is
    # the window's left in the shared desktop space (negative on a left monitor)
    # and py is measured DOWNWARD from the top of the primary screen -- the same
    # space JS reports via e.screenX / e.screenY during a drag.

    def screens(self):
        try:
            return list(webview.screens) if getattr(webview, "screens", None) else []
        except Exception:
            return []

    def primary_height(self):
        for s in self.screens():
            if int(getattr(s, "x", 0) or 0) == 0 and int(getattr(s, "y", 0) or 0) == 0:
                return int(s.height)
        scr = self.screens()
        return int(scr[0].height) if scr else 900

    def active_screen(self):
        scr = self.screens()
        if not scr:
            return None
        i = self.active_idx if 0 <= self.active_idx < len(scr) else 0
        return scr[i]

    def resting_full(self):
        return not self.settings.get("compact", True)

    def current_width(self):
        full = self.peeking or self.resting_full()
        key = "width_full" if full else "width_compact"
        return int(self.settings.get(key, 260 if full else 92))

    def _native_window(self):
        return getattr(self.window, "native", None)

    def _place_topleft(self, gx, py):
        # Place the window's TOP-LEFT at global x = gx and py pixels down from the
        # PRIMARY screen's top. Cocoa's global space is y-up with the primary at
        # origin (0,0), so the primary's top sits at y = primary_height; a point
        # py below it is at Cocoa y = primary_height - py. setFrameTopLeftPoint_
        # then handles the window height for us. This is anchor-independent.
        win = self._native_window()
        if win is None:
            try:
                self.window.move(int(gx), int(py))  # fallback (primary anchor only)
            except Exception:
                pass
            return
        ph = self.primary_height()
        cocoa_pt = (float(gx), float(ph - py))

        def _do():
            try:
                win.setFrameTopLeftPoint_(cocoa_pt)
            except Exception:
                pass

        if AppHelper is not None:
            try:
                AppHelper.callAfter(_do)   # AppKit calls must run on the main thread
                return
            except Exception:
                pass
        _do()

    def position_window(self):
        if not self.window or self.dragging:
            return  # never yank the window while the user is holding it
        s = self.active_screen()
        if s is None:
            return
        sx = int(getattr(s, "x", 0) or 0)
        sy = int(getattr(s, "y", 0) or 0)
        sw, sh = int(s.width), int(s.height)
        ph = self.primary_height()
        w = self.current_width()
        margin = int(self.settings.get("edge_margin", 8))
        top = int(self.settings.get("top_margin", 36))
        edge = self.settings.get("edge", "right")
        global_left = (sx + sw - w - margin) if edge == "right" else (sx + margin)
        py = self.settings.get("pos_y")
        py = top if py is None else int(py)
        py = max(top, min(py, sh - 90))
        target_top = ph - (sy + sh)          # this screen's top, in primary-down coords
        self._place_topleft(global_left, target_top + py)

    def set_height(self, h):
        self._last_h = int(h)
        try:
            s = self.active_screen()
            sh = int(s.height) if s else 900
            hh = max(64, min(int(h), sh - 50))
            if not self.dragging:
                self.window.resize(self.current_width(), hh)
        except Exception:
            pass
        self.position_window()

    def set_peek(self, full):
        if self.dragging:
            return
        self.peeking = bool(full)
        try:
            self.window.resize(self.current_width(), int(self._last_h or 200))
        except Exception:
            pass
        self.position_window()

    # ---------- drag: free while held, snap to nearest side on release ----------
    # The UI drives the drag with global cursor coordinates, so we move the window
    # directly and decide the destination screen / side only on release.
    def on_moved(self, x, y):
        self._last_pos = (x, y)

    def drag_start(self):
        self.dragging = True

    def move_to_global(self, gx, gy):
        # gx, gy = desired window top-left in global coords (primary-down), as the
        # JS drag handler reports them via e.screenX / e.screenY. Move freely while
        # the user holds; the snap-to-nearest-side happens only in drag_end().
        self._place_topleft(gx, gy)

    def drag_end(self, gx, gy):
        self.dragging = False
        scr = self.screens()
        if not scr:
            self.position_window()
            return
        w = self.current_width()
        cx = float(gx) + w / 2.0
        ph = self.primary_height()
        idx = self.active_idx
        for i, s in enumerate(scr):
            sx = int(getattr(s, "x", 0) or 0)
            if sx <= cx < sx + int(s.width):
                idx = i
                break
        s = scr[idx]
        sx = int(getattr(s, "x", 0) or 0)
        sy = int(getattr(s, "y", 0) or 0)
        sw, sh = int(s.width), int(s.height)
        self.active_idx = idx
        self.settings["monitor"] = idx
        self.settings["edge"] = "left" if (cx - sx) < sw / 2.0 else "right"
        top = int(self.settings.get("top_margin", 36))
        target_top = ph - (sy + sh)
        offset = float(gy) - target_top         # vertical position within that screen
        if self.settings.get("remember_position", True):
            self.settings["pos_y"] = int(max(top, min(int(offset), sh - 90)))
        self.save_settings(self.settings)        # persists, then snaps (no relaunch)

    # ---------- status snapshot ----------
    @staticmethod
    def _pid_alive(pid):
        # PID liveness check via signal 0: doesn't actually signal the process,
        # just probes whether it exists and we're allowed to see it.
        if not pid:
            return True  # no PID recorded (older status file) -- don't reap blind
        try:
            os.kill(int(pid), 0)
            return True
        except ProcessLookupError:
            return False
        except Exception:
            return True  # e.g. PermissionError -- process exists, just not ours

    def snapshot(self):
        items = []
        muted = set(self.settings.get("muted", []))
        now = time.time()
        idle_after = float(self.settings.get("idle_after", 8) or 0)
        for fp in glob.glob(os.path.join(STATUS_DIR, "*.json")):
            try:
                with open(fp) as f:
                    rec = json.load(f)
            except Exception:
                continue
            # Reap signals whose session process is no longer running. Normally
            # the SessionEnd hook deletes the file on a clean exit, but a killed
            # terminal, `kill -9`, crash, or system sleep skips that hook and
            # leaves the file behind forever -- this is the actual backstop.
            if not self._pid_alive(rec.get("pid")):
                try:
                    os.remove(fp)
                except FileNotFoundError:
                    pass
                continue
            # Track sessions whose Stop/Notification hooks are working correctly.
            # When the hook writes "waiting", "done", or "idle" we record the
            # session_id so we never apply the idle_after inference to it again.
            # This prevents false "waiting for input" signals during long thinking
            # phases on terminal Claude sessions (which DO have proper Stop hooks).
            sid = rec.get("session_id")
            if sid and rec.get("status") in ("waiting", "done", "idle"):
                self._sessions_with_hooks.add(sid)

            # IDE sessions (VS Code / JetBrains extension) fire PreToolUse hooks
            # but NOT Stop/Notification, so they never flip from "working" on their
            # own. Once quiet past idle_after we infer they are waiting. We skip
            # this for sessions already known to have working hooks — those use the
            # real hook signal and don't need (or benefit from) this inference.
            if idle_after > 0 and rec.get("status") == "working" \
                    and sid not in self._sessions_with_hooks \
                    and (now - float(rec.get("updated_at", now))) >= idle_after:
                rec["status"] = "waiting"
                rec["label"] = rec.get("label") or "input"
                rec["status_since"] = float(rec.get("updated_at", now))
            rec["muted"] = rec.get("path") in muted
            items.append(rec)

        def sort_key(r):
            mode = self.settings.get("sort", "urgency")
            if mode == "name":
                return (r.get("project", "").lower(),)
            if mode == "recent":
                return (-r.get("updated_at", 0),)
            return (STATUS_RANK.get(r.get("status"), 9), -r.get("status_since", 0))

        # Deduplicate: a single Claude session can write multiple status files
        # (one per cwd) when it navigates between directories. Keep only the
        # most-recently-updated record for each session_id.
        by_session: dict = {}
        no_session = []
        for item in items:
            sid = item.get("session_id")
            if not sid:
                no_session.append(item)
            elif sid not in by_session or item.get("updated_at", 0) > by_session[sid].get("updated_at", 0):
                by_session[sid] = item
        items = no_session + list(by_session.values())

        # Fold subdirectory / same-path sessions into their parent project instead
        # of showing them as separate, unrelated-looking top-level signals. Two
        # cases land here even after the session_id dedup above:
        #   1. Same exact path, different session_id (e.g. one Claude session in a
        #      terminal and another via an IDE extension, both scoped to the same
        #      project root).
        #   2. A path that is a *subdirectory* of another tracked project's path
        #      (e.g. ".../Openclaw/configs" alongside ".../Openclaw") -- Claude
        #      Code was invoked with a nested cwd, which otherwise renders as an
        #      unrelated project named after the subfolder.
        # In both cases we keep one signal at the parent's path/project name and
        # let whichever status is most urgent (see STATUS_RANK) win.
        items.sort(key=lambda r: len(((r.get("path") or "")).rstrip("/")))
        merged: list = []
        for item in items:
            ipath = (item.get("path") or "").rstrip("/")
            parent = None
            for existing in merged:
                epath = (existing.get("path") or "").rstrip("/")
                if epath and (ipath == epath or ipath.startswith(epath + "/")):
                    parent = existing
                    break
            if parent is None:
                merged.append(item)
                continue
            if STATUS_RANK.get(item.get("status"), 9) < STATUS_RANK.get(parent.get("status"), 9):
                parent["status"] = item.get("status")
                parent["label"] = item.get("label", parent.get("label"))
                parent["status_since"] = item.get("status_since", parent.get("status_since"))
            parent["updated_at"] = max(parent.get("updated_at", 0), item.get("updated_at", 0))
        items = merged

        items.sort(key=sort_key)
        return items

    # ---------- notifications ----------
    def detect_transitions(self, items):
        # Key transitions by session_id (falling back to path for sessions without one).
        # This ensures that when Claude changes cwd mid-session (and the panel shows
        # a different path after deduplication), we don't misread it as a new session
        # starting fresh and fire spurious notifications.
        muted = set(self.settings.get("muted", []))
        for r in items:
            path = r.get("path", "")
            key = r.get("session_id") or path
            status = r.get("status")
            if status != self._prev_status.get(key):
                if path not in muted:
                    if status == "waiting" and self.settings.get("notify_on_waiting"):
                        label = r.get("label") or "needs you"
                        self.notify("Claude · " + r.get("project", "project"),
                                    label, "Tap the light to jump in.",
                                    self.settings.get("sound_waiting"))
                    elif status == "done" and self.settings.get("notify_on_done"):
                        self.notify("Claude · " + r.get("project", "project"),
                                    "response complete", "", self.settings.get("sound_done"))
                self._prev_status[key] = status
        live = {r.get("session_id") or r.get("path") for r in items}
        for k in list(self._prev_status):
            if k not in live:
                self._prev_status.pop(k, None)

    def notify(self, title, subtitle, message, sound):
        # Visual banner via osascript (delivered by Script Editor -- needs its
        # notification permission enabled in System Settings to be visible).
        try:
            script = 'display notification %s with title %s' % (
                json.dumps(message or " "), json.dumps(title))
            if subtitle:
                script += ' subtitle %s' % json.dumps(subtitle)
            subprocess.Popen(["osascript", "-e", script],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        # Sound via afplay, decoupled from the banner so it always plays even
        # if notification banners are blocked/denied for Script Editor.
        self.play_sound(sound)

    def play_sound(self, sound):
        # Play a named macOS system sound directly. Used by notifications and by
        # the settings sheet's preview buttons.
        try:
            if sound and sound.lower() != "none":
                snd = os.path.join("/System/Library/Sounds", sound + ".aiff")
                if os.path.exists(snd):
                    subprocess.Popen(["afplay", snd],
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        except Exception:
            pass

    # ---------- watcher ----------
    def watch(self):
        time.sleep(0.4)
        while not self._stop:
            try:
                items = self.snapshot()
                self.detect_transitions(items)
                self.push(items)
            except Exception:
                pass
            time.sleep(max(0.2, float(self.settings.get("poll_interval", 0.6))))

    def hover_watch(self):
        # macOS only delivers mouseenter/mouseleave to a WKWebView when its window
        # is the KEY (focused) window. This panel is almost always non-key -- you're
        # working in your IDE -- so the JS hover handlers never fire: hover wouldn't
        # expand it, and after clicking a project (which focuses the IDE) it would
        # stay full because the collapse-on-leave never arrives. We detect hover here
        # instead, polling the global cursor against the live window frame -- which
        # works regardless of focus -- and feed the result into the same JS peek path.
        if NSEvent is None:
            return
        time.sleep(0.6)
        while not self._stop:
            time.sleep(0.1)
            try:
                if self.dragging:
                    continue
                # Only the compact + hover-expand mode has anything to peek.
                if not (self.settings.get("hover_expand") and self.settings.get("compact")):
                    self._hover_inside = False
                    continue
                win = self._native_window()
                if win is None:
                    continue
                # mouseLocation() and frame() share Cocoa's global space (y-up,
                # primary's bottom-left at the origin), so we can compare directly.
                p = NSEvent.mouseLocation()
                f = win.frame()
                ox, oy = f.origin.x, f.origin.y
                inside = (ox <= p.x <= ox + f.size.width) and \
                         (oy <= p.y <= oy + f.size.height)
                if inside != self._hover_inside:
                    self._hover_inside = inside
                    try:
                        self.window.evaluate_js(
                            "window.__hover && window.__hover(%s)"
                            % ("true" if inside else "false"))
                    except Exception:
                        pass
            except Exception:
                pass

    def push(self, items):
        if not self.window:
            return
        try:
            self.window.evaluate_js("window.__apply && window.__apply(%s)" % json.dumps(items))
        except Exception:
            pass

    def push_settings(self):
        if not self.window:
            return
        try:
            self.window.evaluate_js("window.__settings && window.__settings(%s)"
                                    % json.dumps(self.settings))
        except Exception:
            pass

    # ---------- actions ----------
    # VS Code-family apps ship a CLI shim (`code`, `cursor`, ...) that talks to
    # the already-running instance and FOCUSES an existing window for a folder
    # that's already open there. `open -a <App> <path>` instead goes through
    # LaunchServices' generic "open this document" path, which most of these
    # editors treat as "open a new window" every time -- so clicking the same
    # signal repeatedly kept spawning duplicate windows. Prefer the CLI shim;
    # fall back to `open -a` for apps that don't have one.
    _IDE_CLI_NAMES = {
        "cursor": "cursor",
        "visual studio code": "code",
        "vscode": "code",
        "vscodium": "codium",
        "windsurf": "windsurf",
    }

    def _ide_cli_path(self, app_name):
        cli = self._IDE_CLI_NAMES.get((app_name or "").strip().lower())
        if not cli:
            return None
        found = shutil.which(cli)
        if found:
            return found
        # Common case: the CLI shim exists inside the .app bundle but was
        # never symlinked onto PATH (e.g. Cursor's "Shell Command: Install
        # 'cursor' command" was never run).
        for base in ("/Applications", os.path.expanduser("~/Applications")):
            candidate = os.path.join(base, app_name + ".app",
                                      "Contents/Resources/app/bin", cli)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        return None

    # Where each editor keeps its live window state (VS Code-family apps all
    # use the same globalStorage/storage.json shape under their own support
    # folder).
    _IDE_STORAGE_DIRS = {
        "cursor": "Cursor",
        "visual studio code": "Code",
        "vscode": "Code",
        "vscodium": "VSCodium",
        "windsurf": "Windsurf",
    }

    def _uri_to_path(self, uri):
        try:
            u = urlparse(uri)
            if u.scheme != "file":
                return None
            return os.path.realpath(unquote(u.path))
        except Exception:
            return None

    def _resolve_open_target(self, path, app_name):
        """Bare `open -a <App> <path>` correctly reuses/focuses an existing
        window when that path was itself opened as a standalone folder --
        that's already working. It can't match when `path` is really just
        one root *inside* an already-open multi-root workspace (e.g. a
        `.code-workspace` file listing it alongside sibling folders) --
        there, the window's identity is the *workspace file*, not any one of
        its folders, so the bare path never matches and a duplicate
        single-folder window gets created instead.

        We resolve that by reading the editor's own persisted window state
        (globalStorage/storage.json -> windowsState) and, if `path` turns up
        as a folder inside a currently-open workspace file, returning that
        workspace file's path instead -- which *does* match the open window.
        Falls back to `path` unchanged if nothing can be determined (covers
        the already-working standalone-folder case, and any failure mode).
        """
        folder = self._IDE_STORAGE_DIRS.get((app_name or "").strip().lower())
        if not folder:
            return path
        storage = os.path.join(HOME, "Library/Application Support", folder,
                                "User/globalStorage/storage.json")
        try:
            with open(storage) as f:
                data = json.load(f)
        except Exception:
            return path
        ws = data.get("windowsState", {})
        entries = list(ws.get("openedWindows") or [])
        last = ws.get("lastActiveWindow")
        if last:
            entries.append(last)
        target = os.path.realpath(path)
        for entry in entries:
            wsid = (entry or {}).get("workspaceIdentifier") or {}
            cfg = wsid.get("configURIPath")
            if not cfg:
                continue
            ws_file = self._uri_to_path(cfg)
            if not ws_file or not os.path.isfile(ws_file):
                continue
            try:
                with open(ws_file) as f:
                    ws_data = json.load(f)
            except Exception:
                continue
            base = os.path.dirname(ws_file)
            for fentry in ws_data.get("folders", []) or []:
                fp = fentry.get("path")
                if not fp:
                    continue
                resolved = os.path.realpath(
                    fp if os.path.isabs(fp) else os.path.join(base, fp))
                if resolved == target:
                    return ws_file
        return path

    def open_ide(self, path, app_name=""):
        path = os.path.expanduser(path or "")
        for app in [a for a in (app_name, self.settings.get("default_ide_app"),
                                self.settings.get("fallback_ide_app")) if a]:
            target = self._resolve_open_target(path, app)
            cli = self._ide_cli_path(app)
            if cli:
                try:
                    if subprocess.run([cli, target],
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL).returncode == 0:
                        return True
                except Exception:
                    pass
            try:
                if subprocess.run(["open", "-a", app, target],
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL).returncode == 0:
                    return True
            except Exception:
                continue
        subprocess.Popen(["open", path])
        return False

    def open_terminal(self, path):
        try:
            subprocess.Popen(["open", "-a", self.settings.get("terminal_app", "Terminal"),
                              os.path.expanduser(path or "")])
        except Exception:
            pass

    def copy_path(self, path):
        try:
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(input=(path or "").encode())
        except Exception:
            pass

    def _status_path(self, path):
        import re as _re, hashlib as _h
        cleaned = _re.sub(r"[^A-Za-z0-9_.-]", "_", (path or "").strip("/")) or \
            _h.md5((path or "").encode()).hexdigest()[:10]
        return os.path.join(STATUS_DIR, cleaned[:120] + ".json")

    def force_close(self, path):
        """Send SIGTERM to the Claude process whose cwd matches path, then dismiss."""
        import signal as _sig
        target = os.path.expanduser(path or "").rstrip("/")
        # Use lsof to find 'claude' (or 'node' as fallback) processes with matching cwd.
        for cmd in ("claude", "node"):
            try:
                out = subprocess.run(
                    ["lsof", "-a", "-c", cmd, "-d", "cwd", "-F", "pn"],
                    capture_output=True, text=True, timeout=5,
                )
                cur_pid = None
                for line in out.stdout.splitlines():
                    if line.startswith("p"):
                        cur_pid = line[1:]
                    elif line.startswith("n") and cur_pid:
                        if line[1:].rstrip("/") == target:
                            try:
                                os.kill(int(cur_pid), _sig.SIGTERM)
                            except Exception:
                                pass
            except Exception:
                pass
        self.dismiss(path)

    def dismiss(self, path):
        try:
            os.remove(self._status_path(path))
        except FileNotFoundError:
            pass
        self.push(self.snapshot())

    def acknowledge(self, path):
        # Called when the user opens a finished ("done") project. Clearing it back
        # to "ready" so the green light doesn't linger after you've seen it.
        fp = self._status_path(path)
        try:
            with open(fp) as f:
                rec = json.load(f)
        except Exception:
            return
        if rec.get("status") != "done":
            return
        now = time.time()
        rec.update(status="idle", label="", status_since=now, updated_at=now)
        tmp = fp + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(rec, f)
            os.replace(tmp, fp)
        except Exception:
            return
        self._prev_status[path] = "idle"   # don't treat the next poll as a new transition
        self.push(self.snapshot())

    def set_mute(self, path, muted):
        m = set(self.settings.get("muted", []))
        m.add(path) if muted else m.discard(path)
        self.settings["muted"] = sorted(m)
        self.save_settings(self.settings)

    def save_settings(self, new):
        for k, v in (new or {}).items():
            if k in DEFAULT_SETTINGS:
                self.settings[k] = v
                if k == "monitor":
                    self.active_idx = int(v or 0)
        try:
            os.makedirs(APP_DIR, exist_ok=True)
            with open(SETTINGS_FILE, "w") as f:
                json.dump(self.settings, f, indent=2)
        except Exception:
            pass
        self.push_settings()
        self.position_window()

    def quit(self):
        self._stop = True
        try:
            self.window.destroy()
        except Exception:
            pass

    # ---------- startup ----------
    def on_start(self):
        time.sleep(0.3)
        self._prepare_native_window()
        self.position_window()
        threading.Thread(target=self.watch, daemon=True).start()
        threading.Thread(target=self.hover_watch, daemon=True).start()

    def _prepare_native_window(self):
        # Let the panel track the cursor and forward drags even while it isn't the
        # focused window -- so hover and header-drags stay responsive in one motion.
        win = self._native_window()
        if win is None:
            return

        def _do():
            try:
                win.setAcceptsMouseMovedEvents_(True)
            except Exception:
                pass

        if AppHelper is not None:
            try:
                AppHelper.callAfter(_do)
                return
            except Exception:
                pass
        _do()


class Api:
    def __init__(self, app):
        self.app = app

    def get_initial(self):
        n = len(list(webview.screens)) if getattr(webview, "screens", None) else 1
        return {"settings": self.app.settings, "state": self.app.snapshot(), "monitors": n}

    def open_ide(self, path, app_name=""):
        self.app.open_ide(path, app_name)

    def open_terminal(self, path):
        self.app.open_terminal(path)

    def copy_path(self, path):
        self.app.copy_path(path)

    def force_close(self, path):
        self.app.force_close(path)

    def dismiss(self, path):
        self.app.dismiss(path)

    def acknowledge(self, path):
        self.app.acknowledge(path)

    def set_mute(self, path, muted):
        self.app.set_mute(path, bool(muted))

    def save_settings(self, settings):
        self.app.save_settings(settings)

    def set_height(self, h):
        self.app.set_height(h)

    def set_peek(self, full):
        self.app.set_peek(full)

    def preview_sound(self, name):
        self.app.play_sound(name)

    def drag_start(self):
        self.app.drag_start()

    def move_to_global(self, gx, gy):
        self.app.move_to_global(gx, gy)

    def drag_end(self, gx, gy):
        self.app.drag_end(gx, gy)

    def quit(self):
        self.app.quit()


def main():
    url = UI_FILE
    if not os.path.exists(url):
        local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "index.html")
        url = local if os.path.exists(local) else UI_FILE

    app = App()
    width = app.current_width()

    # Always anchor to the primary screen (origin 0,0). With this anchor,
    # window.move() takes global coordinates, so we can place the panel on any
    # display by passing global x/y -- no per-display window assignment needed.
    app.window = webview.create_window(
        "Claude Monitor",
        url=url,
        js_api=app.api,
        width=width,
        height=200,
        frameless=True,
        easy_drag=False,
        on_top=True,
        transparent=True,
        resizable=False,
        min_size=(70, 60),
        background_color="#10131A",
    )
    try:
        app.window.events.moved += app.on_moved
    except Exception:
        pass

    webview.start(app.on_start, debug=False)


if __name__ == "__main__":
    main()
