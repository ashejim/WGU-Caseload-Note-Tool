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

# The bundled safe actions the tours point at (ship in default_scenarios.yaml).
# The note tour falls back to any 'test'-named group if its action is absent.
WALKTHROUGH_ACTION = "Try me - file a test note"
WALKTHROUGH_BATCH_ACTION = "Try me - welcome email (batch)"

# The tour runs in phases; Skip / the last-step button advance to the NEXT phase
# rather than ending the whole thing. The final phase ("encryption") explains
# at-rest encryption and, on finish, the app offers to set it up.
_PHASE_ORDER = ["note", "batch", "encryption"]

# A darker, saturated royal blue (not the app's lighter sky-blue accents) so the
# highlight stands out against a busy screen. Borders are drawn thick too.
_ACCENT = "#1d4ed8"
_HL_WIDTH = 5      # spotlight rectangle around a highlighted widget
_BORDER = 4        # bubble / card / button-highlight border
_BUBBLE_W = 460


class Walkthrough:
    def __init__(self, app, tour: str = "note"):
        self.app = app
        self.tour = tour           # "note" (golden path) or "batch"
        self.root = app.root
        self.steps: list[dict] = []
        self.i = 0
        self._dim = None        # dim overlay (canvas w/ highlight)
        self._canvas = None
        self._bubble = None     # explanation bubble (narrate)
        self._pill = None       # floating instruction card (do / checklist)
        self._cfg_after = None
        self._active = False
        # Checklist step state (auto-checking items + an arrow at the target).
        self._arrow = None
        self._checklist_after = None
        self._checklist_items: list = []   # list of item dicts
        self._manual_checked: dict = {}    # idx -> bool (user-ticked items)
        self._continue_btn = None          # gated until all items are checked
        self._highlight_action = ""

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

    def _finish(self, completed: bool = True, advancing: bool = False) -> None:
        self._active = False
        self._clear_checklist()
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
        # A true end (not just advancing to the next phase) lets the app do its
        # post-walkthrough follow-up — namely offer at-rest encryption.
        if not advancing:
            try:
                self.app._on_walkthrough_ended()
            except Exception:
                pass

    # ------------------------------------------------------------ navigation
    def _next_phase(self):
        try:
            i = _PHASE_ORDER.index(self.tour)
        except ValueError:
            return None
        return _PHASE_ORDER[i + 1] if i + 1 < len(_PHASE_ORDER) else None

    def _skip_phase(self) -> None:
        """Skip the current phase → go to the next one (or end after the last)."""
        nxt = self._next_phase()
        if nxt:
            self._goto_tour(nxt)
        else:
            self._finish(completed=False)

    def _advance_or_finish(self) -> None:
        nxt = self._next_phase()
        if nxt:
            self._goto_tour(nxt)
        else:
            self._finish(completed=True)

    def _next(self) -> None:
        if self.i >= len(self.steps) - 1:
            self._advance_or_finish()
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
        self._clear_checklist()   # tear down any prior checklist arrow/poll
        step = self.steps[self.i]
        kind = step.get("kind")
        if kind == "checklist":
            self._render_checklist(step)
        elif kind == "do":
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
            # Recovery: clicking the grey area brings the bubble back to the
            # front (in case a window move buried it), and Esc exits the tour —
            # so the dim can never trap the user.
            self._canvas.bind(
                "<Button-1>", lambda _e: self._recover_bubble())
            self._dim.bind("<Escape>", lambda _e: self._finish(completed=False))
        self._dim.deiconify()
        self._dim.geometry(f"{rw}x{rh}+{rx}+{ry}")
        self._draw_highlight()

        # Bubble.
        if self._bubble is None:
            self._bubble = ctk.CTkToplevel(self.root)
            self._bubble.overrideredirect(True)
            self._bubble.attributes("-topmost", True)
            self._bubble.bind(
                "<Escape>", lambda _e: self._finish(completed=False))
        else:
            for w in self._bubble.winfo_children():
                w.destroy()
        self._bubble.deiconify()
        self._fill_bubble(self._bubble, step)
        self._bubble.update_idletasks()
        self._place_near_target(self._bubble)
        self._raise(self._dim)
        self._raise(self._bubble)

    def _enable_drag(self, win, *handles) -> None:
        """Let the user drag `win` by pressing on any of `handles` (its title /
        counter labels) — so the card can be moved off whatever it's covering."""
        st = {"x": 0, "y": 0}

        def press(e):
            st["x"], st["y"] = e.x_root, e.y_root

        def drag(e):
            dx, dy = e.x_root - st["x"], e.y_root - st["y"]
            st["x"], st["y"] = e.x_root, e.y_root
            try:
                win.geometry(
                    f"+{win.winfo_rootx() + dx}+{win.winfo_rooty() + dy}")
            except Exception:
                pass

        for w in handles:
            try:
                w.configure(cursor="fleur")
            except Exception:
                pass
            w.bind("<ButtonPress-1>", press, add="+")
            w.bind("<B1-Motion>", drag, add="+")

    def _recover_bubble(self) -> None:
        """Bring the bubble/card back above the dim (a click-on-grey recovery)."""
        for w in (self._dim,):
            if w is not None:
                self._raise(w)
        for w in (self._bubble, self._pill):
            if w is not None:
                try:
                    if w.winfo_ismapped():
                        self._raise(w)
                except Exception:
                    pass

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
        pad = 6
        # Draw a couple of concentric rectangles so the spotlight reads as a
        # bold band, not a thin line, against a busy screen.
        c.create_rectangle(x - pad, y - pad, x + w + pad, y + h + pad,
                           outline=_ACCENT, width=_HL_WIDTH)
        c.create_rectangle(x - pad - _HL_WIDTH, y - pad - _HL_WIDTH,
                           x + w + pad + _HL_WIDTH, y + h + pad + _HL_WIDTH,
                           outline=_ACCENT, width=2)

    def _fill_bubble(self, parent, step: dict, is_do: bool = False) -> None:
        frame = ctk.CTkFrame(
            parent, corner_radius=12, border_width=_BORDER, border_color=_ACCENT,
            width=_BUBBLE_W)
        frame.pack(fill="both", expand=True)
        n = len(self.steps)
        counter = ctk.CTkLabel(
            frame, text=f"⠿  Walkthrough · {self.i + 1} of {n}   (drag to move)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=(_ACCENT, _ACCENT), anchor="w",
        )
        counter.pack(fill="x", padx=22, pady=(16, 2))
        title = ctk.CTkLabel(
            frame, text=step.get("title", ""),
            font=ctk.CTkFont(size=23, weight="bold"),
            anchor="w", justify="left", wraplength=_BUBBLE_W - 44,
        )
        title.pack(fill="x", padx=22, pady=(2, 8))
        self._enable_drag(parent, frame, counter, title)
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
        skip_label = "Skip ▸" if self._next_phase() else "Skip tour"
        ctk.CTkButton(
            btns, text=skip_label, width=96, height=38,
            font=ctk.CTkFont(size=13),
            fg_color="transparent", border_width=1,
            border_color=("gray70", "gray45"),
            text_color=("gray30", "gray70"), hover_color=("gray85", "gray25"),
            command=self._skip_phase,
        ).pack(side="left")
        last = self.i >= len(self.steps) - 1
        if last:
            nxt_label = "Next phase ▸" if self._next_phase() else "Finish"
        else:
            nxt_label = "Continue ▸" if is_do else "Next ▸"
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
        if not self._active or self.steps[self.i].get("kind") in ("do",
                                                                  "checklist"):
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
            # CRITICAL: after moving the dim, re-raise the bubble ABOVE it —
            # else the (click-capturing) dim ends up on top and the user is
            # trapped behind a grey screen with no reachable buttons.
            self._raise(self._dim)
            if self._bubble is not None:
                self._raise(self._bubble)
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

    # ------------------------------------------------------- checklist step
    def _student_selected(self) -> bool:
        panel = getattr(self.app, "caseload_panel", None)
        if panel is None:
            return False
        try:
            if panel._checked_rows():
                return True
            if panel._focused_row() is not None:
                return True
        except Exception:
            pass
        return False

    def _action_fired(self) -> bool:
        _, action = self._fire_target()
        last = getattr(self.app, "_last_fired_action", "") or ""
        return (last == action) if action else bool(last)

    def _note_filling(self) -> bool:
        """True once the fire-time pop-up is done and the note is being filled
        in Salesforce (i.e., the user completed the pop-up)."""
        _, action = self._fire_target()
        started = getattr(self.app, "_note_fill_started", "") or ""
        return (started == action) if action else bool(started)

    def _selected_student_name(self) -> str:
        """Display name of the currently selected/highlighted student, or ''."""
        panel = getattr(self.app, "caseload_panel", None)
        if panel is None:
            return ""
        row = None
        try:
            rows = panel._checked_rows()
            row = rows[0] if rows else panel._focused_row()
        except Exception:
            row = None
        if not row:
            return ""
        return str(row.get("Name", "") or row.get("Student Name", "")
                   or "").strip()

    def _target_button(self):
        """The visible action button to point the arrow at (or None)."""
        panel = getattr(self.app, "action_panel", None)
        if panel is None or not self._highlight_action:
            return None
        btn = (getattr(panel, "buttons", None) or {}).get(self._highlight_action)
        try:
            if btn is not None and btn.winfo_exists() and btn.winfo_ismapped():
                return btn
        except Exception:
            return None
        return None

    def _render_checklist(self, step: dict) -> None:
        # Step aside so the real UI is usable (like a DO step).
        for w in (self._dim, self._bubble):
            if w is not None:
                try: w.withdraw()
                except Exception: pass
        # If the step highlights an action (target_fn), reveal its group so the
        # button renders + gets the arrow. Steps without a target_fn (e.g. the
        # batch "add a filter" checklist) don't highlight anything.
        target_fn = self.steps[self.i].get("target_fn")
        group, action = target_fn() if callable(target_fn) else (None, "")
        panel = getattr(self.app, "action_panel", None)
        if group and panel is not None:
            try: panel.reveal_group(group)
            except Exception: pass
        try:
            self.app._last_fired_action = ""
            self.app._note_fill_started = ""
        except Exception:
            pass
        self._highlight_action = action or ""

        if self._pill is None:
            self._pill = ctk.CTkToplevel(self.root)
            self._pill.overrideredirect(True)
            self._pill.attributes("-topmost", True)
        else:
            for w in self._pill.winfo_children():
                w.destroy()
        self._pill.deiconify()
        self._fill_checklist(self._pill, step)
        self._pill.update_idletasks()
        rx, ry, rw, rh = self._root_box()
        pw = self._pill.winfo_reqwidth()
        ph = self._pill.winfo_reqheight()
        self._pill.geometry(f"+{rx + rw - pw - 24}+{ry + rh - ph - 24}")
        self._raise(self._pill)
        # Draw attention once, then keep the arrow + poll running.
        btn = self._target_button()
        if btn is not None:
            self._pulse_widget(btn, times=4)
        self._poll_checklist()

    def _fill_checklist(self, parent, step: dict) -> None:
        self._checklist_items = []
        frame = ctk.CTkFrame(
            parent, corner_radius=12, border_width=_BORDER, border_color=_ACCENT,
            width=_BUBBLE_W)
        frame.pack(fill="both", expand=True)
        n = len(self.steps)
        counter = ctk.CTkLabel(
            frame, text=f"⠿  Walkthrough · {self.i + 1} of {n}   (drag to move)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=(_ACCENT, _ACCENT), anchor="w",
        )
        counter.pack(fill="x", padx=22, pady=(16, 2))
        title = ctk.CTkLabel(
            frame, text=step.get("title", ""),
            font=ctk.CTkFont(size=21, weight="bold"),
            anchor="w", justify="left", wraplength=_BUBBLE_W - 44,
        )
        title.pack(fill="x", padx=22, pady=(2, 6))
        self._enable_drag(parent, frame, counter, title)
        if step.get("intro"):
            ctk.CTkLabel(
                frame, text=step["intro"],
                font=ctk.CTkFont(size=14), text_color=("gray20", "gray85"),
                anchor="w", justify="left", wraplength=_BUBBLE_W - 44,
            ).pack(fill="x", padx=22, pady=(0, 8))
        # Optional action button (e.g. "Open the action editor") above the items.
        action = step.get("action")
        if action is not None:
            ctk.CTkButton(
                frame, text=step.get("action_label", "Open"),
                height=40, font=ctk.CTkFont(size=14, weight="bold"),
                command=lambda: self._run_action(action),
            ).pack(fill="x", padx=22, pady=(0, 10))
        for idx, item in enumerate(step.get("items", [])):
            done_fn = item.get("done")
            manual = not callable(done_fn)   # None → user ticks it by clicking
            text_fn = item.get("text_fn")    # dynamic label text
            text = text_fn() if callable(text_fn) else item.get("text", "")
            lbl = ctk.CTkLabel(
                frame, text=f"☐  {text}",
                font=ctk.CTkFont(size=15), text_color=("gray15", "gray90"),
                anchor="w", justify="left", wraplength=_BUBBLE_W - 44,
                cursor=("hand2" if manual else ""),
            )
            lbl.pack(fill="x", padx=22, pady=(2, 0))
            if manual:
                lbl.bind("<Button-1>", lambda _e, i=idx: self._toggle_manual(i))
            # Optional bold emphasis sub-line (e.g. the selected student name).
            emph_fn = item.get("emphasis_fn")
            emph_lbl = None
            if callable(emph_fn):
                emph_lbl = ctk.CTkLabel(
                    frame, text=f"      {emph_fn() or ''}",
                    font=ctk.CTkFont(size=15, weight="bold"),
                    text_color=("gray10", "white"), anchor="w", justify="left",
                    wraplength=_BUBBLE_W - 44,
                    cursor=("hand2" if manual else ""))
                emph_lbl.pack(fill="x", padx=22, pady=(0, 2))
                if manual:
                    emph_lbl.bind(
                        "<Button-1>", lambda _e, i=idx: self._toggle_manual(i))
            self._checklist_items.append(
                {"lbl": lbl, "done": done_fn, "text": text, "text_fn": text_fn,
                 "emph_lbl": emph_lbl, "emph_fn": emph_fn,
                 "manual": manual, "idx": idx})
        if step.get("note"):
            ctk.CTkLabel(
                frame, text="↳ " + step["note"],
                font=ctk.CTkFont(size=12), text_color=("gray45", "gray60"),
                anchor="w", justify="left", wraplength=_BUBBLE_W - 44,
            ).pack(fill="x", padx=22, pady=(6, 4))
        btns = ctk.CTkFrame(frame, fg_color="transparent")
        btns.pack(fill="x", padx=22, pady=(6, 16))
        ctk.CTkButton(
            btns, text=("Skip ▸" if self._next_phase() else "Skip"), width=80,
            height=38, font=ctk.CTkFont(size=13),
            fg_color="transparent", border_width=1,
            border_color=("gray70", "gray45"),
            text_color=("gray30", "gray70"), hover_color=("gray85", "gray25"),
            command=self._skip_phase,
        ).pack(side="left")
        last = self.i >= len(self.steps) - 1
        if last:
            cont_label = "Next phase ▸" if self._next_phase() else "Finish"
        else:
            cont_label = "Continue ▸"
        # Continue stays disabled (grey, not blue) until every item is checked,
        # so the user actually completes the steps before advancing.
        self._continue_btn = ctk.CTkButton(
            btns, text=cont_label, width=130,
            height=38, font=ctk.CTkFont(size=14, weight="bold"),
            command=self._next,
        )
        self._continue_btn.pack(side="right")
        self._refresh_checklist()
        if self.i > 0:
            ctk.CTkButton(
                btns, text="◂ Back", width=84, height=38,
                font=ctk.CTkFont(size=13), fg_color="transparent",
                border_width=1, border_color=("gray70", "gray45"),
                text_color=("gray30", "gray70"),
                hover_color=("gray85", "gray25"), command=self._back,
            ).pack(side="right", padx=(0, 8))

    def _item_done(self, it) -> bool:
        if it["manual"]:
            return bool(self._manual_checked.get(it["idx"], False))
        try:
            return bool(it["done"]())
        except Exception:
            return False

    def _all_items_done(self) -> bool:
        return bool(self._checklist_items) and all(
            self._item_done(it) for it in self._checklist_items)

    def _refresh_checklist(self) -> None:
        """Repaint each item's ☐/☑ — auto items from their done() probe, manual
        items from the user's ticks — and gate the Continue button on all-done."""
        for it in self._checklist_items:
            done = self._item_done(it)
            if callable(it.get("text_fn")):     # refresh dynamic label text
                try:
                    it["text"] = it["text_fn"]()
                except Exception:
                    pass
            # Manual items check off by a click, not automatically — say so
            # (only while unchecked) so it's clearly the user's to do, unlike
            # the auto ones above it.
            label_text = it["text"]
            if it["manual"] and not done:
                label_text += "    · tap to check ·"
            try:
                it["lbl"].configure(
                    text=f"{'☑' if done else '☐'}  {label_text}",
                    text_color=((_ACCENT, _ACCENT) if done
                                else ("gray15", "gray90")))
            except Exception:
                pass
            if it.get("emph_lbl") is not None and callable(it.get("emph_fn")):
                try:
                    it["emph_lbl"].configure(text=f"      {it['emph_fn']() or ''}")
                except Exception:
                    pass
        # Gate Continue: enabled (blue) only once every item is checked.
        if self._continue_btn is not None:
            try:
                if self._all_items_done():
                    self._continue_btn.configure(state="normal")
                else:
                    self._continue_btn.configure(state="disabled")
            except Exception:
                pass

    def _toggle_manual(self, idx: int) -> None:
        self._manual_checked[idx] = not self._manual_checked.get(idx, False)
        self._refresh_checklist()

    def _poll_checklist(self) -> None:
        if not self._active or self.steps[self.i].get("kind") != "checklist":
            return
        self._refresh_checklist()
        # Keep the arrow pinned to the (possibly rebuilt) target button.
        btn = self._target_button()
        if btn is not None:
            try:
                btn.configure(border_width=_BORDER, border_color=_ACCENT)
            except Exception:
                pass
            self._position_arrow(btn)
        elif self._arrow is not None:
            try: self._arrow.withdraw()
            except Exception: pass
        try:
            self._checklist_after = self.root.after(500, self._poll_checklist)
        except Exception:
            pass

    def _position_arrow(self, btn) -> None:
        if self._arrow is None:
            self._arrow = ctk.CTkToplevel(self.root)
            self._arrow.overrideredirect(True)
            self._arrow.attributes("-topmost", True)
            ctk.CTkLabel(
                self._arrow, text="👈", font=ctk.CTkFont(size=30),
            ).pack()
        try:
            self._arrow.deiconify()
            self._arrow.update_idletasks()
            aw = self._arrow.winfo_reqwidth()
            ah = self._arrow.winfo_reqheight()
            x = btn.winfo_rootx() + btn.winfo_width() + 4
            y = btn.winfo_rooty() + (btn.winfo_height() - ah) // 2
            self._arrow.geometry(f"+{x}+{y}")
            self._arrow.lift()
            self._arrow.attributes("-topmost", True)
        except Exception:
            pass

    def _clear_checklist(self) -> None:
        if self._checklist_after:
            try: self.root.after_cancel(self._checklist_after)
            except Exception: pass
            self._checklist_after = None
        if self._arrow is not None:
            try: self._arrow.destroy()
            except Exception: pass
            self._arrow = None
        # Drop the highlight border on the target button if it's still around.
        try:
            panel = getattr(self.app, "action_panel", None)
            btn = (getattr(panel, "buttons", None) or {}).get(
                self._highlight_action) if panel else None
            if btn is not None and btn.winfo_exists():
                btn.configure(border_width=0)
        except Exception:
            pass
        self._checklist_items = []
        self._manual_checked = {}
        self._continue_btn = None
        self._highlight_action = ""

    def _pulse_widget(self, w, times: int = 6, on_ms: int = 240) -> None:
        """Flash a thick accent border on a widget a few times to draw the eye,
        then restore its original border. Non-destructive."""
        try:
            orig_bw = w.cget("border_width")
            orig_bc = w.cget("border_color")
        except Exception:
            return
        state = {"n": 0}

        def _step():
            try:
                if not w.winfo_exists():
                    return
            except Exception:
                return
            on = (state["n"] % 2 == 0)
            try:
                w.configure(border_width=_BORDER if on else orig_bw,
                            border_color=_ACCENT if on else orig_bc)
            except Exception:
                return
            state["n"] += 1
            if state["n"] < times:
                try:
                    w.after(on_ms, _step)
                except Exception:
                    pass
            else:
                try:
                    w.configure(border_width=orig_bw, border_color=orig_bc)
                except Exception:
                    pass

        _step()

    # ---- batch tour helpers ----
    def _batch_target(self):
        """(group_name, action_name) for the bundled batch welcome action, or
        (None, '') if it's absent."""
        app = self.app
        scenarios = getattr(app, "scenarios", None) or {}
        groups = getattr(app, "groups", None) or []
        if WALKTHROUGH_BATCH_ACTION in scenarios:
            for g in groups:
                if WALKTHROUGH_BATCH_ACTION in (getattr(g, "scenarios", None)
                                                or []):
                    return g.name, WALKTHROUGH_BATCH_ACTION
            return "", WALKTHROUGH_BATCH_ACTION
        return None, ""

    def _batch_fired(self) -> bool:
        return (getattr(self.app, "_last_fired_action", "") or "") \
            == WALKTHROUGH_BATCH_ACTION

    def _editing_batch_action(self) -> bool:
        """True when the editor is open ON the batch action (auto-checks the
        'open it in the editor' step)."""
        return (getattr(self.app, "_editor_visible", False)
                and getattr(self.app, "_current_scenario", "")
                == WALKTHROUGH_BATCH_ACTION)

    def _goto_tour(self, name: str) -> None:
        """Finish this phase and immediately launch the next (e.g. note → batch).
        advancing=True so the end-of-walkthrough follow-up doesn't fire yet."""
        self._finish(completed=True, advancing=True)
        try:
            self.app._start_walkthrough(tour=name)
        except Exception:
            pass

    def _build_steps(self) -> list:
        if self.tour == "batch":
            return self._build_batch_steps()
        if self.tour == "encryption":
            return self._build_encryption_steps()
        return self._build_note_steps()

    def _build_encryption_steps(self) -> list:
        return [
            {"kind": "narrate", "target": None,
             "title": "Last thing — lock down your local data",
             "body": "Everything this tool touches stays on THIS computer — the "
                     "caseload, history, notes, success-path data. NOTHING is "
                     "uploaded anywhere; it only talks to Salesforce/Mongoose in "
                     "the browser you drive. For extra peace of mind you can "
                     "encrypt those local files with an app password, so they're "
                     "unreadable if this computer is lost or the files are copied "
                     "off it. It's optional and over-the-top safe."},
            {"kind": "narrate", "target": None,
             "title": "Set it up when you click Finish",
             "body": "Click Finish and you'll be offered a quick password setup "
                     "(you can also choose 'Not now'). One important catch: there "
                     "is NO recovery if you forget the password — store it "
                     "somewhere safe. Reopen any tour anytime from ❔ Help."},
        ]

    def _build_batch_steps(self) -> list:
        app = self.app
        group, action = self._batch_target()
        act = action or "the welcome-email batch action"
        return [
            {"kind": "narrate", "target": None,
             "title": "Now try a batch — reach many students at once",
             "body": "A batch fires one action across every student that "
                     "matches its filters — ideal for welcome emails to newly "
                     "assigned students. You'll review the students AND every "
                     "email first, and NOTHING is sent or recorded until the "
                     "very last step — so it's safe to follow along."},
            {"kind": "narrate",
             "target": lambda: getattr(app, "action_panel", None)
             and app.action_panel.frame,
             "title": "The welcome-email batch",
             "body": f"“{act}” emails a welcome to every student matching its "
                     "filters (it fills their preferred name and course code). "
                     "Right now it's filtered to students with no ACI contact "
                     "yet — newly assigned students you haven't reached."},
            {"kind": "checklist",
             "title": "Add a course filter — you drive this",
             "intro": "Let's limit it to ONE of your courses so it doesn't email "
                      "every new student. The button below opens the editor right "
                      "on this action — then add a filter.",
             "action_label": "✎ Open this action in the editor",
             "action": lambda: app._open_editor(WALKTHROUGH_BATCH_ACTION),
             "items": [
                 {"text": "Editor open on the welcome-email batch",
                  "done": self._editing_batch_action},
                 {"text": "In its Filters, click '+ Add filter' and set:  "
                          "Course Code — is — <your course>", "done": None},
                 {"text": "Click Save, then ✓ Done to leave the editor",
                  "done": None},
             ],
             "note": "Tick the manual boxes as you finish them; Continue lights "
                     "up once all three are checked."},
            {"kind": "checklist",
             "title": "Fire it — then STOP at the review",
             "intro": "Now fire the batch. You get a two-step review: first the "
                      "matched students, then each email. Everything stays safe "
                      "until you press Send.",
             "target_fn": self._batch_target,
             "items": [
                 {"text": f"Click “{act}” to fire the batch",
                  "done": self._batch_fired},
                 {"text": "Review the matched students, then click ✓ Start",
                  "done": None},
                 {"text": "Review each welcome email in the preview",
                  "done": None},
             ],
             "note": "⚠  The email preview's Send button emails these students "
                     "FOR REAL. Click Cancel unless you truly want to send — "
                     "nothing has been sent or recorded yet, so cancelling is "
                     "completely safe.  (If it says “no matches”, that's fine — "
                     "it just means every student in that course has already "
                     "been contacted. You've still seen the flow.)",
             "danger": True},
            {"kind": "narrate", "target": None,
             "title": "⚠  Remember: Cancel unless you mean it",
             "body": "That's the batch flow: filter → matched students → review "
                     "each email → Send. The final Send emails students FOR "
                     "REAL, so cancel unless you're ready. Reopen either tour "
                     "anytime from ❔ Help. Nice work!"},
        ]

    def _build_note_steps(self) -> list:
        app = self.app
        group, action = self._fire_target()
        has_fire = bool(group) or bool(action)
        if action:
            fire_intro = (
                f"Filing a note is the heart of the app — let's do one safely. "
                f"“{action}” sends no email or text, and nothing files until you "
                f"press Submit in Salesforce.")
            click_item = f"Click “{action}” — the highlighted button (👈)"
        else:
            fire_intro = (
                "Filing a note is the heart of the app — let's do one safely. "
                "Pick a Test action; it opens a note for you to review.")
            click_item = "Click a Test action — the highlighted button (👈)"
        fire_step = {
            "kind": "checklist",
            "title": "Try it: file a test note",
            "intro": fire_intro,
            "target_fn": self._fire_target,
            "items": [
                {"text": "Find and select a student in the caseload",
                 "done": self._student_selected},
                {"text": click_item, "done": self._action_fired},
                {"text": "In the pop-up, check the course code and note look "
                         "right, then press Continue",
                 "done": self._note_filling},
                {"text": "In Salesforce, go to this student's open tab and "
                         "click Submit — or close the tab to discard:",
                 "emphasis_fn": lambda: (
                     self._selected_student_name() or "the selected student"),
                 "done": None},
            ],
            "note": "The last one you tick off yourself (Salesforce hands the "
                    "note to you). Safe to try: no email or text, and nothing "
                    "files until you Submit in Salesforce.",
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
             "title": "Nicely done — that's the core loop",
             "body": "Pick a student, fire an action, review, done. Next up: a "
                     "batch — send a welcome email to a whole group at once. "
                     "Click Next phase, or Skip to move on."})
        return steps
