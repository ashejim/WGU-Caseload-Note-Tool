"""An interactive, opt-in first-run walkthrough (a spotlight product tour).

Guides a new user along a short "golden path" — where the action pane is, how
groups/tabs work, where to build actions, how firing works — culminating in an
OPTIONAL invitation to fire a safe sample action for real (the existing fire
flow's review dialogs are the guardrails; nothing is auto-fired here).

Two kinds of step:
  - NARRATE: a dim overlay + a highlight outline around a real UI element + a
    bubble that explains it, advanced with Back / Skip / Next.
  - DO: the overlay steps aside so the real UI is fully usable; a small floating
    card gives an instruction (optionally with a button that opens the real
    dialog, e.g. the group editor) and a "Continue" to resume.

Design notes:
  - `target` is a *callable* returning the widget to highlight (looked up live,
    so a not-yet-built panel doesn't crash construction); None = centered.
  - The tour never changes app data itself — DO steps hand the user the real
    dialogs. So it's safe to run, re-run, or abandon at any point.
  - Progressive "lessons" beyond this golden path are intentionally NOT here yet
    (ship the path, prove it, then extend).
"""
from typing import Callable, Optional

import customtkinter as ctk

from src.config import save_settings

# The bundled safe action the walkthrough's guided-fire step points at (ships in
# default_scenarios.yaml). Falls back to any 'test'-named group if absent.
WALKTHROUGH_ACTION = "Try me - file a test note"

_ACCENT = "#4a9eff"
_BUBBLE_W = 460


class Walkthrough:
    def __init__(self, app):
        self.app = app
        self.root = app.root
        self.steps: list[dict] = []
        self.i = 0
        self._dim = None        # dim overlay (canvas w/ highlight)
        self._canvas = None
        self._bubble = None     # explanation bubble (narrate)
        self._pill = None       # floating instruction card (do)
        self._cfg_after = None
        self._active = False

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._active:
            return
        self._active = True
        self.steps = self._build_steps()
        self.i = 0
        # The tour anchors its overlay to the main window — make sure it's
        # restored and raised, else the spotlight lands off-screen (a minimized
        # window reports its position at -32000).
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.update_idletasks()
        except Exception:
            pass
        try:
            self.root.bind("<Configure>", self._on_root_configure, add="+")
        except Exception:
            pass
        self._render()

    def _raise(self, win) -> None:
        """Force an overlay window to the front. overrideredirect + -topmost is
        flaky on Windows while the app is busy at startup, so re-assert it once
        the window is up (and again a beat later)."""
        try:
            win.deiconify()
            win.lift()
            win.attributes("-topmost", True)
            win.after(30, lambda: win.winfo_exists()
                      and win.attributes("-topmost", True))
        except Exception:
            pass

    def _finish(self, completed: bool = True) -> None:
        self._active = False
        for w in ("_dim", "_bubble", "_pill"):
            win = getattr(self, w, None)
            if win is not None:
                try:
                    win.destroy()
                except Exception:
                    pass
                setattr(self, w, None)
        try:
            self.root.unbind("<Configure>")
        except Exception:
            pass
        try:
            self.app.settings.walkthrough_done = True
            save_settings(self.app.settings)
        except Exception:
            pass

    # ------------------------------------------------------------ navigation
    def _next(self) -> None:
        if self.i >= len(self.steps) - 1:
            self._finish(completed=True)
            return
        self.i += 1
        self._render()

    def _back(self) -> None:
        if self.i > 0:
            self.i -= 1
            self._render()

    # -------------------------------------------------------------- geometry
    def _target_widget(self):
        step = self.steps[self.i]
        getter = step.get("target")
        if not getter:
            return None
        try:
            w = getter()
            if w is not None and w.winfo_exists() and w.winfo_ismapped():
                return w
        except Exception:
            pass
        return None

    def _root_box(self):
        r = self.root
        return (r.winfo_rootx(), r.winfo_rooty(),
                r.winfo_width(), r.winfo_height())

    # ---------------------------------------------------------------- render
    def _render(self) -> None:
        if not self._active:
            return
        step = self.steps[self.i]
        if step.get("kind") == "do":
            self._render_do(step)
        else:
            self._render_narrate(step)

    def _render_narrate(self, step: dict) -> None:
        if self._pill is not None:
            try: self._pill.destroy()
            except Exception: pass
            self._pill = None
        rx, ry, rw, rh = self._root_box()
        # Dim overlay covering the main window.
        if self._dim is None:
            self._dim = ctk.CTkToplevel(self.root)
            self._dim.overrideredirect(True)
            self._dim.attributes("-topmost", True)
            try:
                self._dim.attributes("-alpha", 0.55)
            except Exception:
                pass
            self._canvas = ctk.CTkCanvas(
                self._dim, highlightthickness=0, bg="#0a0a0a")
            self._canvas.pack(fill="both", expand=True)
        self._dim.deiconify()
        self._dim.geometry(f"{rw}x{rh}+{rx}+{ry}")
        self._draw_highlight()

        # Bubble.
        if self._bubble is None:
            self._bubble = ctk.CTkToplevel(self.root)
            self._bubble.overrideredirect(True)
            self._bubble.attributes("-topmost", True)
        else:
            for w in self._bubble.winfo_children():
                w.destroy()
        self._bubble.deiconify()
        self._fill_bubble(self._bubble, step)
        self._bubble.update_idletasks()
        self._place_near_target(self._bubble)
        self._raise(self._dim)
        self._raise(self._bubble)

    def _render_do(self, step: dict) -> None:
        # Step aside so the real UI is usable; show a compact floating card.
        if self._dim is not None:
            try: self._dim.withdraw()
            except Exception: pass
        if self._bubble is not None:
            try: self._bubble.withdraw()
            except Exception: pass
        if self._pill is None:
            self._pill = ctk.CTkToplevel(self.root)
            self._pill.overrideredirect(True)
            self._pill.attributes("-topmost", True)
        else:
            for w in self._pill.winfo_children():
                w.destroy()
        self._pill.deiconify()
        self._fill_bubble(self._pill, step, is_do=True)
        self._pill.update_idletasks()
        # Pin the card to the bottom-right of the main window (out of the way of
        # the dialogs the user is about to use).
        rx, ry, rw, rh = self._root_box()
        pw = self._pill.winfo_reqwidth()
        ph = self._pill.winfo_reqheight()
        self._pill.geometry(f"+{rx + rw - pw - 24}+{ry + rh - ph - 24}")
        self._raise(self._pill)

    def _draw_highlight(self) -> None:
        c = self._canvas
        c.delete("all")
        rx, ry, rw, rh = self._root_box()
        c.configure(width=rw, height=rh)
        tw = self._target_widget()
        if tw is None:
            return
        try:
            x = tw.winfo_rootx() - rx
            y = tw.winfo_rooty() - ry
            w = tw.winfo_width()
            h = tw.winfo_height()
        except Exception:
            return
        pad = 5
        c.create_rectangle(x - pad, y - pad, x + w + pad, y + h + pad,
                           outline=_ACCENT, width=3)

    def _fill_bubble(self, parent, step: dict, is_do: bool = False) -> None:
        frame = ctk.CTkFrame(
            parent, corner_radius=12, border_width=3, border_color=_ACCENT,
            width=_BUBBLE_W)
        frame.pack(fill="both", expand=True)
        n = len(self.steps)
        ctk.CTkLabel(
            frame, text=f"Walkthrough · {self.i + 1} of {n}",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=(_ACCENT, _ACCENT), anchor="w",
        ).pack(fill="x", padx=22, pady=(16, 2))
        ctk.CTkLabel(
            frame, text=step.get("title", ""),
            font=ctk.CTkFont(size=23, weight="bold"),
            anchor="w", justify="left", wraplength=_BUBBLE_W - 44,
        ).pack(fill="x", padx=22, pady=(2, 8))
        ctk.CTkLabel(
            frame, text=step.get("body", ""),
            font=ctk.CTkFont(size=16), text_color=("gray15", "gray88"),
            anchor="w", justify="left", wraplength=_BUBBLE_W - 44,
        ).pack(fill="x", padx=22, pady=(0, 14))

        # Optional action button (opens a real dialog for a DO step).
        action = step.get("action")
        if action is not None:
            ctk.CTkButton(
                frame, text=step.get("action_label", "Open"),
                height=42, font=ctk.CTkFont(size=15, weight="bold"),
                command=lambda: self._run_action(action),
            ).pack(fill="x", padx=22, pady=(0, 12))

        btns = ctk.CTkFrame(frame, fg_color="transparent")
        btns.pack(fill="x", padx=22, pady=(0, 16))
        ctk.CTkButton(
            btns, text="Skip tour", width=96, height=38,
            font=ctk.CTkFont(size=13),
            fg_color="transparent", border_width=1,
            border_color=("gray70", "gray45"),
            text_color=("gray30", "gray70"), hover_color=("gray85", "gray25"),
            command=lambda: self._finish(completed=False),
        ).pack(side="left")
        last = self.i >= len(self.steps) - 1
        nxt_label = ("Finish" if last else ("Continue ▸" if is_do else "Next ▸"))
        ctk.CTkButton(
            btns, text=nxt_label, width=130, height=38,
            font=ctk.CTkFont(size=14, weight="bold"), command=self._next,
        ).pack(side="right")
        if self.i > 0:
            ctk.CTkButton(
                btns, text="◂ Back", width=84, height=38,
                font=ctk.CTkFont(size=13),
                fg_color="transparent", border_width=1,
                border_color=("gray70", "gray45"),
                text_color=("gray30", "gray70"),
                hover_color=("gray85", "gray25"),
                command=self._back,
            ).pack(side="right", padx=(0, 8))

    def _run_action(self, action: Callable) -> None:
        try:
            action()
        except Exception:
            pass

    def _place_near_target(self, win) -> None:
        rx, ry, rw, rh = self._root_box()
        bw = win.winfo_reqwidth() or _BUBBLE_W
        bh = win.winfo_reqheight() or 160
        tw = self._target_widget()
        if tw is None:
            x = rx + (rw - bw) // 2
            y = ry + (rh - bh) // 2
        else:
            tx = tw.winfo_rootx()
            ty = tw.winfo_rooty()
            th = tw.winfo_height()
            twd = tw.winfo_width()
            # Prefer below the target; flip above if it would run off-screen.
            x = min(max(tx, rx + 8), rx + rw - bw - 8)
            y = ty + th + 10
            if y + bh > ry + rh - 8:
                y = ty - bh - 10
            x = tx + twd + 12 if (y < ry) else x
        # Clamp to the app window's box (NOT the primary screen — that would
        # yank the bubble onto the wrong monitor when the app is on a secondary
        # display).
        x = max(rx, min(x, rx + rw - bw))
        y = max(ry, min(y, ry + rh - bh))
        win.geometry(f"+{int(x)}+{int(y)}")

    def _on_root_configure(self, _e=None) -> None:
        if not self._active or self.steps[self.i].get("kind") == "do":
            return
        if self._cfg_after:
            try: self.root.after_cancel(self._cfg_after)
            except Exception: pass
        self._cfg_after = self.root.after(120, self._reposition)

    def _reposition(self) -> None:
        self._cfg_after = None
        if not self._active or self._dim is None:
            return
        rx, ry, rw, rh = self._root_box()
        try:
            self._dim.geometry(f"{rw}x{rh}+{rx}+{ry}")
            self._draw_highlight()
            if self._bubble is not None:
                self._place_near_target(self._bubble)
        except Exception:
            pass

    # ----------------------------------------------------------------- steps
    def _fire_target(self):
        """(group_name, action_name) for the guided fire step, or (None, '').
        Prefers the bundled safe walkthrough action; falls back to any
        'test'-named group so a user's own Test group still works."""
        app = self.app
        scenarios = getattr(app, "scenarios", None) or {}
        groups = getattr(app, "groups", None) or []
        if WALKTHROUGH_ACTION in scenarios:
            for g in groups:
                if WALKTHROUGH_ACTION in (getattr(g, "scenarios", None) or []):
                    return g.name, WALKTHROUGH_ACTION
            return "", WALKTHROUGH_ACTION      # present but ungrouped
        for g in groups:
            if "test" in (g.name or "").lower():
                return g.name, ""
        return None, ""

    def _reveal_fire_group(self) -> None:
        group, _ = self._fire_target()
        panel = getattr(self.app, "action_panel", None)
        if group and panel is not None:
            try:
                panel.reveal_group(group)
            except Exception:
                pass

    def _build_steps(self) -> list:
        app = self.app
        group, action = self._fire_target()
        has_fire = bool(group) or bool(action)
        if action:
            fire_body = (
                f"Click a student in the caseload to select them, then click "
                f"“{action}”. It's safe: no email or text — it just opens a note "
                f"for you to review, and nothing is filed until you press Submit "
                f"yourself. Click Continue when you've tried it — or skip and do "
                f"it whenever.")
            fire_label = f"Show me “{action}”"
        else:
            fire_body = (
                "Click a student in the caseload to select them, then click an "
                "action in your Test group — these are safe to fire. Anything "
                "that emails or texts shows a review first, so nothing goes out "
                "without your OK. Click Continue when you've tried one — or skip.")
            fire_label = "Show the Test actions"
        fire_step = {
            "kind": "do", "target": None,
            "title": "Try it: fire a safe action",
            "body": fire_body,
            "action_label": fire_label,
            "action": self._reveal_fire_group,
        }
        steps = [
            {"kind": "narrate", "target": None,
             "title": "Welcome — let's take two minutes",
             "body": "A quick tour of where things are and how to file your "
                     "first note. You can skip anytime, and reopen this from "
                     "❔ Help."},
            {"kind": "narrate",
             "target": lambda: getattr(app, "action_panel", None)
             and app.action_panel.frame,
             "title": "Your actions live here",
             "body": "Each button files a note (and can send an email or text) "
                     "for the student you've selected. Related actions are "
                     "grouped into tabs; click a tab to switch groups, and "
                     "📌 pins a group open above the tabs."},
            {"kind": "narrate",
             "target": lambda: getattr(app, "caseload_panel", None)
             and app.caseload_panel.frame,
             "title": "Pick a student here",
             "body": "This is your caseload. Click a row to select a student "
                     "(or tick several). The action you fire runs on whoever's "
                     "selected — no need to search Salesforce first."},
            {"kind": "narrate",
             "target": lambda: getattr(app, "editor_toggle_btn", None),
             "title": "Build your own actions",
             "body": "✎ Edit actions is where you create and tweak actions and "
                     "groups. We've included a few samples to start — including "
                     "a 🧪 Test group of safe ones."},
            {"kind": "do",
             "target": lambda: getattr(app, "editor_toggle_btn", None),
             "title": "Try it: make a group",
             "body": "Groups keep related actions together. Open the group "
                     "editor, give it a name (and an optional short name for "
                     "its tab), then Save. Come back and click Continue.",
             "action_label": "＋ Open the group editor",
             "action": lambda: app._add_group()},
            {"kind": "narrate", "target": None,
             "title": "How firing works",
             "body": "Select a student, then click an action. Anything that "
                     "emails or texts always shows you a review first, so "
                     "nothing goes out without your OK. A filed note can be "
                     "edited afterward if needed."},
        ]
        # Optional hands-on finale: fire a safe sample action. Only offered when
        # there's a safe target to point at (skip cleanly otherwise).
        if has_fire:
            steps.append(fire_step)
        steps.append(
            {"kind": "narrate", "target": None,
             "title": "You're all set",
             "body": "That's the whole loop: pick a student, fire an action, "
                     "review, done. Reopen this tour anytime from ❔ Help — "
                     "happy filing!"})
        return steps
