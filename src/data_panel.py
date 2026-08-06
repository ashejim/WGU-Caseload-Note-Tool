"""The Data tab — Momentum calibration (predicted vs actual outcomes) and other
caseload analytics, read from the local history DB. A view over the App; data
comes from src.history and the App's cached state.
"""
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from src import history
from src.config import save_settings
from src.ui_common import SECONDARY_BTN_KWARGS


class DataPanel:
    """Analytics/graphs shown as a 'Data' tab in the activity area, with a
    pop-out/dock option (mirrors the caseload panel). A view-selector dropdown
    keeps it extensible — more charts/tables drop in without new tabs. First
    view: actual student pass rate vs. the Momentum-predicted band, drawn on a
    native tk.Canvas (no plotting dependency, to keep the build lean)."""

    # Views (label -> key). Extensible: add a builder + an entry here.
    _VIEWS = {"Pass rate vs prediction": "calibration",
              "Momentum risk": "atrisk",
              "Momentum trajectory": "trajectory",
              "Pass rate over time": "overtime",
              "Completion by month": "completion"}
    # Short labels for the on-screen view switcher (segmented button — must stay
    # compact so all fit the narrow docked pane).
    _VIEW_LABELS = {"Calibration": "calibration", "Risk": "atrisk",
                    "Trajectory": "trajectory", "Over time": "overtime",
                    "Completion": "completion"}
    # Completion-view month axis (label -> history.completion_by_month `by`).
    _COMPL_BY = {"By course start": "start", "By resolution": "resolution"}
    # Which Momentum reading drives the predicted line (entry vs at-outcome).
    _COMPL_BASIS = {"Entry momentum": "entry", "Exit momentum": "exit"}
    # Calibration basis + course-load options (label -> key), mirroring the
    # 📈 Momentum dialog so the two stay consistent.
    _BASES = {"Entry — fair": "entry", "Entry — proxy": "all",
              "Exit — diagnostic": "exit"}
    # Student-focus filter for the trajectory view — relabeled so it's clearly
    # about the student's course load (1 vs 2+ courses), NOT picking a course.
    _LOADS = {"All": "all", "Focused (1 course)": "single",
              "Juggling (2+)": "multi"}
    # Distinct, stable colors for per-course calibration series (by course
    # index in the sorted course list, so a course keeps its color).
    _COURSE_PALETTE = ["#4a9eff", "#3fb950", "#e0844f", "#b072e0",
                       "#e0c84a", "#46c7c7", "#d76aa8", "#9aa0a6"]
    # Resolution-date window presets (label -> days back from today; None=all).
    _DATE_RANGES = {"All dates": None, "Last 30 days": 30, "Last 90 days": 90,
                    "Last 6 months": 182, "Last 12 months": 365}

    def __init__(self, app) -> None:
        self.app = app
        self.tab = None             # the docked Data-tab frame (constant)
        self.window = None          # pop-out Toplevel when popped
        self.popped = False
        self.view = "calibration"
        self.basis = "entry"
        self.load = "all"
        self.courses = None         # set of selected course codes (None=all)
        self.date_days = None       # resolution-date window (days back; None=all)
        self.ctrls = None
        self.content = None
        self.canvas = None
        self._data = None           # calibration cache
        self._traj = None           # trajectory cache
        self._over = None           # over-time cache
        self._compl = None          # completion-by-month cache
        self.compl_by = "start"     # completion month axis
        self.compl_basis = "entry"  # Momentum reading for the predicted line
        self._ar_show_dismissed = False   # risk list: reveal dismissed rows
        self._ar_window = None            # momentum window (weeks; None=all)

    # ---- mount / pop-out -------------------------------------------------
    def attach(self, tab) -> None:
        """Bind to the docked Data-tab frame and build into it."""
        self.tab = tab
        self.mount(tab)

    def mount(self, parent) -> None:
        """(Re)build the whole panel into ``parent`` (the tab or a pop-out)."""
        for w in parent.winfo_children():
            w.destroy()
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)        # content row expands

        # ONE controls row, rebuilt per view: the view selector sits with the
        # view's own options (so it stays in the same visible box, never split
        # onto a row that gets squeezed off). Pop-out lives in the always-visible
        # log header instead (see App._popout_data_panel).
        self.ctrls = ctk.CTkFrame(parent, fg_color="transparent")
        self.ctrls.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 2))

        self.content = ctk.CTkFrame(parent, fg_color="transparent")
        self.content.grid(row=1, column=0, sticky="nsew", padx=4, pady=(2, 2))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.status = ctk.CTkLabel(
            parent, text="", font=ctk.CTkFont(size=10), justify="left",
            anchor="w", text_color=("gray40", "gray65"), wraplength=560)
        self.status.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 4))
        self._build_view()

    def _build_view(self) -> None:
        """Rebuild the controls row (view selector + the active view's options)
        and the content, so only what applies to the current view is shown."""
        for w in self.ctrls.winfo_children():
            w.destroy()
        for w in self.content.winfo_children():
            w.destroy()
        self.canvas = None
        # View selector — always first in the controls row.
        ctk.CTkLabel(self.ctrls, text="View:").pack(side="left", padx=(0, 4))
        view_label = next((k for k, v in self._VIEW_LABELS.items()
                           if v == self.view), list(self._VIEW_LABELS)[0])
        vm = ctk.CTkOptionMenu(
            self.ctrls, width=120, values=list(self._VIEW_LABELS),
            command=lambda v: self._select_view(
                self._VIEW_LABELS.get(v, "calibration")))
        vm.set(view_label)
        vm.pack(side="left", padx=(0, 10))
        # Dock button only while popped (besides closing the window).
        if self.popped:
            ctk.CTkButton(self.ctrls, text="⧉ Dock", width=70,
                          command=self._dock,
                          **SECONDARY_BTN_KWARGS).pack(side="right")
        v = self.view
        if v == "atrisk":
            self._build_atrisk_controls(self.ctrls)
            self._view_atrisk(self.content)
        elif v == "trajectory":
            self._build_trajectory_controls(self.ctrls)
            self._view_trajectory(self.content)
        elif v == "overtime":
            self._build_overtime_controls(self.ctrls)
            self._view_overtime(self.content)
        elif v == "completion":
            self._build_completion_controls(self.ctrls)
            self._view_completion(self.content)
        else:
            self._build_calibration_controls(self.ctrls)
            self._view_calibration(self.content)

    # ---- per-view option controls ---------------------------------------
    def _course_color(self, i):
        return self._COURSE_PALETTE[i % len(self._COURSE_PALETTE)]

    @staticmethod
    def _blend(c1: str, c2: str, t: float) -> str:
        """Blend hex color c1 toward c2 by fraction t (0→c1, 1→c2). Used to
        fade a course color toward the canvas background for a 'faint' bar."""
        try:
            a, b = c1.lstrip("#"), c2.lstrip("#")
            ch = [round(int(a[i:i+2], 16) * (1 - t) + int(b[i:i+2], 16) * t)
                  for i in (0, 2, 4)]
            return "#{:02x}{:02x}{:02x}".format(*ch)
        except Exception:
            return c1

    def _date_bounds(self):
        """(date_from, date_to) ISO strings for the selected window, or
        (None, None) for all dates. Window filters by RESOLUTION date."""
        if not self.date_days:
            return (None, None)
        import datetime as _dt
        today = _dt.date.today()
        return ((today - _dt.timedelta(days=self.date_days)).isoformat(),
                today.isoformat())

    def _build_date_control(self, parent) -> None:
        ctk.CTkLabel(parent, text="Dates:").pack(side="left", padx=(10, 4))
        cur = next((k for k, v in self._DATE_RANGES.items()
                    if v == self.date_days), "All dates")
        dm = ctk.CTkOptionMenu(
            parent, width=120, values=list(self._DATE_RANGES),
            command=lambda v: self._set_dates(self._DATE_RANGES.get(v)))
        dm.set(cur)
        dm.pack(side="left")

    def _build_overtime_controls(self, parent) -> None:
        self._build_date_control(parent)

    def _set_dates(self, days) -> None:
        self.date_days = days
        self._recompute_current()

    def _build_calibration_controls(self, opts) -> None:
        self.basis_menu = ctk.CTkOptionMenu(
            opts, width=150, values=list(self._BASES),
            command=lambda v: self._set("basis", self._BASES.get(v, "entry")))
        self.basis_menu.set(next((k for k, v in self._BASES.items()
                                  if v == self.basis), "Entry — fair"))
        self.basis_menu.pack(side="left")
        ctk.CTkLabel(opts, text="Courses:").pack(side="left", padx=(10, 4))
        codes = history.course_codes()
        if self.courses is None:
            self.courses = set(codes)           # default: show all courses
        for i, code in enumerate(codes):
            var = ctk.BooleanVar(value=(code in self.courses))
            color = self._course_color(i)
            # Checkbox FILL = the course's bar color (so the tick matches the
            # series); the code text stays default (black in light mode).
            ctk.CTkCheckBox(
                opts, text=code, variable=var, width=20,
                checkbox_width=15, checkbox_height=15,
                font=ctk.CTkFont(size=11), fg_color=color, hover_color=color,
                command=lambda c=code, vv=var: self._toggle_course(c, vv),
            ).pack(side="left", padx=(0, 6))
        self._build_date_control(opts)

    def _build_trajectory_controls(self, opts) -> None:
        ctk.CTkLabel(opts, text="Student focus:").pack(side="left", padx=(0, 4))
        self.load_menu = ctk.CTkOptionMenu(
            opts, width=160, values=list(self._LOADS),
            command=lambda v: self._set("load", self._LOADS.get(v, "all")))
        self.load_menu.set(next((k for k, v in self._LOADS.items()
                                 if v == self.load), "All"))
        self.load_menu.pack(side="left")
        self._build_date_control(opts)

    def _toggle_course(self, code, var) -> None:
        if var.get():
            self.courses.add(code)
        else:
            self.courses.discard(code)
        self._recompute_current()

    def _recompute_current(self) -> None:
        """Clear the active view's cache and redraw (after a control change)."""
        if self.view == "calibration":
            self._data = None
            self._render_calibration()
        elif self.view == "trajectory":
            self._traj = None
            self._render_trajectory()
        elif self.view == "overtime":
            self._over = None
            self._render_overtime()
        elif self.view == "completion":
            self._compl = None
            self._render_completion()

    def _select_view(self, key) -> None:
        self.view = key
        self._build_view()

    def _set(self, field, value) -> None:
        setattr(self, field, value)
        if self.view == "calibration":
            self._data = None           # force recompute on the new basis/load
            self._render_calibration()
        elif self.view == "trajectory":
            self._traj = None
            self._render_trajectory()

    def _toggle_popout(self) -> None:
        self._dock() if self.popped else self._pop_out()

    def _pop_out(self) -> None:
        win = ctk.CTkToplevel(self.app.root)
        win.title("Data")
        win.minsize(440, 320)
        geo = (getattr(self.app.settings, "data_window_geometry", "") or "").strip()
        win.geometry(geo if geo else "780x540")
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(0, weight=1)
        win.protocol("WM_DELETE_WINDOW", self._dock)
        self.window = win
        self.popped = True
        body = ctk.CTkFrame(win)
        body.grid(row=0, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)
        self.mount(body)
        self._show_tab_placeholder()
        win.after(80, win.lift)

    def _dock(self) -> None:
        win = self.window
        if win is not None:
            try:
                self.app.settings.data_window_geometry = win.geometry()
                save_settings(self.app.settings)
            except Exception:
                pass
            try:
                win.destroy()
            except Exception:
                pass
        self.window = None
        self.popped = False
        if self.tab is not None:
            self.mount(self.tab)

    def _show_tab_placeholder(self) -> None:
        """While popped out, the in-tab area shows a dock prompt."""
        if self.tab is None:
            return
        for w in self.tab.winfo_children():
            w.destroy()
        box = ctk.CTkFrame(self.tab, fg_color="transparent")
        box.grid(row=0, column=0)
        ctk.CTkLabel(box, text="Data panel is in its own window.",
                     text_color=("gray40", "gray65")).pack(pady=(20, 8))
        ctk.CTkButton(box, text="⧉ Dock", width=90, command=self._dock,
                      **SECONDARY_BTN_KWARGS).pack()

    # ---- data + drawing --------------------------------------------------
    def refresh(self) -> None:
        """Recompute the current view after a fresh outcomes ingest — but only
        if it's already been shown, so an unopened Data tab stays free."""
        if self.content is None:
            return
        if self.view == "calibration":
            if self._data is not None:
                self._data = None
                self._render_calibration()
        elif self.view == "trajectory":
            if self._traj is not None:
                self._traj = None
                self._render_trajectory()
        elif self.view == "overtime":
            if self._over is not None:
                self._over = None
                self._render_overtime()
        elif self.view == "completion":
            if self._compl is not None:
                self._compl = None
                self._render_completion()
        elif self.view == "atrisk":
            self._build_view()

    # ---- view: pass rate vs prediction (chart) --------------------------
    def _view_calibration(self, parent) -> None:
        dark = ctk.get_appearance_mode() == "Dark"
        self.canvas = tk.Canvas(parent, bd=0, highlightthickness=0,
                                bg=("#1d1e1e" if dark else "#f9f9fa"))
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda e: self._on_cal_configure())
        # LAZY: compute on the first real <Configure> (tab shown); later resizes
        # just redraw cached data — no DB hit per frame.

    def _on_cal_configure(self) -> None:
        if self.canvas is None or self.canvas.winfo_width() < 120:
            return
        self._render_calibration() if self._data is None else self._draw()

    def _render_calibration(self) -> None:
        if self.canvas is None:
            return
        codes = history.course_codes()
        sel = self.courses if self.courses is not None else set(codes)
        df, dt_ = self._date_bounds()
        series = []
        for i, code in enumerate(codes):
            if code not in sel:
                continue
            if self.basis == "exit":
                d = history.momentum_calibration_at_exit(
                    course=code, date_from=df, date_to=dt_)
            else:
                elig = "2026-06-10" if self.basis == "entry" else "1900-01-01"
                d = history.momentum_calibration(
                    eligible_from=elig, course=code, date_from=df, date_to=dt_)
            series.append({"course": code, "color": self._course_color(i),
                           "data": d})
        self._data = series
        try:
            cov = history.outcomes_entry_coverage()
        except Exception:
            cov = {"total": 0, "captured": 0, "both": 0, "drifted": 0}
        if not series:
            txt = "Tick at least one course above to show it."
        elif self.basis == "exit":
            drift = f"{cov['drifted']}/{cov['both']}" if cov["both"] else "—"
            txt = ("Exit (diagnostic): self-corrected Momentum — NOT a fair "
                   f"test (changed for {drift} students entry→exit). Per-course "
                   "pass rate vs the predicted band; faint bar = <5 resolved.")
        else:
            lbl = "Entry (fair)" if self.basis == "entry" else "Entry (proxy)"
            txt = (f"{lbl}: per-course pass rate among RESOLVED students vs the "
                   f"model's predicted band. Fair coverage {cov['captured']}/"
                   f"{cov['total']} have an entry reading; faint bar = <5.")
        self.status.configure(text=txt)
        self._draw()

    def _draw(self) -> None:
        c = self.canvas
        if c is None:
            return
        c.delete("all")
        W, H = c.winfo_width(), c.winfo_height()
        if W < 120 or H < 120:
            return
        dark = ctk.get_appearance_mode() == "Dark"
        fg = "#c0c0c0" if dark else "#444444"
        grid = "#333333" if dark else "#dddddd"
        pred_col = "#9aa0a6"
        bg = "#1d1e1e" if dark else "#f9f9fa"   # canvas bg — for faint bars
        series = self._data or []
        L, R, T, B = 44, 16, 26, 54
        pw, ph = W - L - R, H - T - B
        if pw < 60 or ph < 60:
            return

        def y_at(pct):
            return T + ph * (1 - pct / 100.0)

        for g in (0, 25, 50, 75, 100):
            y = y_at(g)
            c.create_line(L, y, L + pw, y, fill=grid)
            c.create_text(L - 6, y, text=str(g), anchor="e", fill=fg,
                          font=("", 8))
        c.create_text(L, 12, anchor="w", fill=fg, font=("", 10, "bold"),
                      text="Actual pass rate vs. Momentum-predicted band (%)")
        if not series:
            c.create_text(W / 2, H / 2, text="Tick at least one course above.",
                          fill=fg)
            return

        nb, ns = 5, len(series)
        for bi in range(nb):
            ref = list(reversed(series[0]["data"]["bands"]))[bi]
            lo, hi = (int(v) for v in ref["predicted_range"].split("-"))
            cx = L + pw * (bi + 0.5) / nb
            zw = pw / nb * 0.78
            c.create_rectangle(cx - zw / 2, y_at(hi), cx + zw / 2, y_at(lo),
                               outline=pred_col, dash=(3, 2))      # target zone
            gw = pw / nb * 0.64
            bw = gw / ns
            for si, s in enumerate(series):
                band = list(reversed(s["data"]["bands"]))[bi]
                rate = band["pass_in_time_rate"]
                if rate is None:
                    continue
                pct = 100 * rate
                bx = cx - gw / 2 + bw * (si + 0.5)
                x0, x1 = bx - bw * 0.42, bx + bw * 0.42
                if band["resolved"] < 5:            # thin sample → faint fill
                    # Faint (not dashed) so 'dashed' means ONLY the predicted
                    # band, matching the legend + the 'faint bar = <5' note.
                    c.create_rectangle(x0, y_at(pct), x1, y_at(0),
                                       fill=self._blend(s["color"], bg, 0.62),
                                       outline="")
                else:
                    c.create_rectangle(x0, y_at(pct), x1, y_at(0),
                                       fill=s["color"], outline="")
                if bw > 22:
                    c.create_text(bx, y_at(pct) - 7, text=str(round(pct)),
                                  fill=fg, font=("", 7, "bold"))
            c.create_text(cx, H - B + 14, text=ref["label"], fill=fg,
                          font=("", 8))
        # legend: course → color (+ total n), then a note
        lx, ly = L, H - 9
        for s in series:
            tot = sum(b["resolved"] for b in s["data"]["bands"])
            c.create_rectangle(lx, ly - 8, lx + 12, ly - 1, fill=s["color"],
                               outline="")
            lab = f"{s['course']} (n={tot})"
            c.create_text(lx + 15, ly - 4, text=lab, anchor="w", fill=fg,
                          font=("", 8))
            lx += 26 + len(lab) * 6
        c.create_text(lx + 6, ly - 4, anchor="w", fill=pred_col, font=("", 8),
                      text="⌐ dashed = predicted band")

    # ---- view: Momentum trajectory (drift bars) -------------------------
    def _view_trajectory(self, parent) -> None:
        dark = ctk.get_appearance_mode() == "Dark"
        self.canvas = tk.Canvas(parent, bd=0, highlightthickness=0,
                                bg=("#1d1e1e" if dark else "#f9f9fa"))
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda e: self._on_traj_configure())

    def _on_traj_configure(self) -> None:
        if self.canvas is None or self.canvas.winfo_width() < 120:
            return
        self._render_trajectory() if self._traj is None else self._draw_trajectory()

    def _render_trajectory(self) -> None:
        if self.canvas is None:
            return
        df, dt_ = self._date_bounds()
        self._traj = history.momentum_drift(course_load=self.load,
                                            date_from=df, date_to=dt_)
        lbl = {"all": "all loads", "single": "single-course only",
               "multi": "multi-course only"}.get(self.load, self.load)
        self.status.configure(text=(
            f"Momentum drift entry→exit for the {self._traj['total']} resolved "
            f"students with both readings ({lbl}). 'Improved' = Momentum rose by "
            "exit, 'declined' = fell. This is exactly why exit Momentum can't "
            "fairly score the model — it drifts toward the outcome (note how "
            "Med-High entrants mostly rise to High)."))
        self._draw_trajectory()

    def _draw_trajectory(self) -> None:
        c = self.canvas
        if c is None or not self._traj:
            return
        c.delete("all")
        W, H = c.winfo_width(), c.winfo_height()
        if W < 160 or H < 120:
            return
        dark = ctk.get_appearance_mode() == "Dark"
        fg = "#c0c0c0" if dark else "#444444"
        col_imp, col_same, col_dec = "#3fb950", "#888888", "#e0524f"
        L, R, T, B = 70, 50, 38, 30
        pw, ph = W - L - R, H - T - B
        if pw < 60 or ph < 40:
            return
        c.create_text(L, 14, anchor="w", fill=fg, font=("", 10, "bold"),
                      text="Momentum drift: entry → exit (by entry band)")
        bands = self._traj["bands"]                    # High → Low
        n = len(bands)
        rh = ph / n
        barh = min(rh * 0.55, 26)
        maxtot = max((b["total"] for b in bands), default=0) or 1
        for i, b in enumerate(bands):
            cy = T + rh * (i + 0.5)
            c.create_text(L - 6, cy, anchor="e", fill=fg, font=("", 9),
                          text=b["label"])
            tot = b["total"]
            bw = pw * (tot / maxtot) if maxtot else 0
            x = L
            for cnt, color in ((b["declined"], col_dec), (b["same"], col_same),
                               (b["improved"], col_imp)):
                if tot and cnt:
                    seg = bw * cnt / tot
                    c.create_rectangle(x, cy - barh / 2, x + seg, cy + barh / 2,
                                       fill=color, outline="")
                    if seg > 16:
                        c.create_text(x + seg / 2, cy, text=str(cnt),
                                      fill="#ffffff", font=("", 8, "bold"))
                    x += seg
            c.create_text(L + bw + 6, cy, anchor="w", fill=fg, font=("", 8),
                          text=f"n={tot}")
        ly = H - 10
        for lbl, color, dx in (("declined", col_dec, 0), ("same", col_same, 92),
                               ("improved", col_imp, 168)):
            c.create_rectangle(L + dx, ly - 7, L + dx + 12, ly - 1, fill=color,
                               outline="")
            c.create_text(L + dx + 16, ly - 4, anchor="w", fill=fg,
                          font=("", 8), text=lbl)

    # ---- view: pass rate over time (bars + rate line) -------------------
    def _view_overtime(self, parent) -> None:
        dark = ctk.get_appearance_mode() == "Dark"
        self.canvas = tk.Canvas(parent, bd=0, highlightthickness=0,
                                bg=("#1d1e1e" if dark else "#f9f9fa"))
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda e: self._on_over_configure())

    def _on_over_configure(self) -> None:
        if self.canvas is None or self.canvas.winfo_width() < 120:
            return
        self._render_overtime() if self._over is None else self._draw_overtime()

    def _render_overtime(self) -> None:
        if self.canvas is None:
            return
        df, dt_ = self._date_bounds()
        self._over = history.outcomes_over_time(date_from=df, date_to=dt_)
        wks = self._over["weeks"]
        tot = sum(w["total"] for w in wks)
        self.status.configure(text=(
            f"Resolved outcomes by week — {tot} across {len(wks)} weeks. Bars "
            "stack passed (green) + not-passed (red); the blue line is that "
            "week's pass rate (right axis). Only resolutions in the past are "
            "shown; a non-pass whose deadline is still future appears once its "
            "term ends. Early data is pass-enriched, so rates run high."))
        self._draw_overtime()

    def _draw_overtime(self) -> None:
        c = self.canvas
        if c is None or not self._over:
            return
        c.delete("all")
        W, H = c.winfo_width(), c.winfo_height()
        if W < 160 or H < 120:
            return
        dark = ctk.get_appearance_mode() == "Dark"
        fg = "#c0c0c0" if dark else "#444444"
        grid = "#333333" if dark else "#dddddd"
        rate_col = "#4a9eff"
        weeks = self._over["weeks"]
        L, R, T, B = 34, 38, 26, 44
        pw, ph = W - L - R, H - T - B
        if pw < 60 or ph < 50:
            return
        c.create_text(L, 12, anchor="w", fill=fg, font=("", 10, "bold"),
                      text="Resolved outcomes by week + pass rate")
        if not weeks:
            c.create_text(W / 2, H / 2, fill=fg,
                          text="No resolved outcomes in range yet.")
            return
        maxct = max((w["total"] for w in weeks), default=1) or 1
        n = len(weeks)
        slot = pw / n

        def y_ct(v):
            return T + ph * (1 - v / maxct)

        def y_pct(p):
            return T + ph * (1 - p / 100.0)

        for p in (0, 50, 100):                         # right axis = %
            y = y_pct(p)
            c.create_line(L, y, L + pw, y, fill=grid)
            c.create_text(L + pw + 6, y, anchor="w", fill=rate_col,
                          text=f"{p}%", font=("", 8))
        c.create_text(L - 4, y_ct(maxct), anchor="e", fill=fg,    # left axis
                      text=str(maxct), font=("", 8))
        bw = min(slot * 0.6, 42)
        pts = []
        for i, wk in enumerate(weeks):
            cx = L + slot * (i + 0.5)
            base = y_ct(0)
            yp = y_ct(wk["passed"])
            if wk["passed"]:
                c.create_rectangle(cx - bw / 2, yp, cx + bw / 2, base,
                                   fill="#3fb950", outline="")
            if wk["not_passed"]:
                c.create_rectangle(cx - bw / 2, y_ct(wk["total"]), cx + bw / 2,
                                   yp, fill="#e0524f", outline="")
            if wk["rate"] is not None:
                pts.append((cx, y_pct(100 * wk["rate"])))
            c.create_text(cx, H - B + 12, text=wk["week"][5:], fill=fg,
                          font=("", 7))
        for i in range(len(pts) - 1):
            c.create_line(*pts[i], *pts[i + 1], fill=rate_col, width=2)
        for cx, cy in pts:
            c.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill=rate_col,
                          outline="")
        ly = H - 8
        c.create_rectangle(L, ly - 7, L + 12, ly - 1, fill="#3fb950",
                           outline="")
        c.create_text(L + 16, ly - 4, anchor="w", fill=fg, font=("", 8),
                      text="passed")
        c.create_rectangle(L + 78, ly - 7, L + 90, ly - 1, fill="#e0524f",
                           outline="")
        c.create_text(L + 94, ly - 4, anchor="w", fill=fg, font=("", 8),
                      text="not passed")
        c.create_line(L + 182, ly - 4, L + 204, ly - 4, fill=rate_col, width=2)
        c.create_text(L + 208, ly - 4, anchor="w", fill=fg, font=("", 8),
                      text="pass rate")

    # ---- view: completion by month (bars + actual/estimate lines) --------
    def _build_completion_controls(self, opts) -> None:
        ctk.CTkLabel(opts, text="Month:").pack(side="left", padx=(0, 4))
        am = ctk.CTkOptionMenu(
            opts, width=150, values=list(self._COMPL_BY),
            command=lambda v: self._set_compl_by(self._COMPL_BY.get(v, "start")))
        am.set(next((k for k, v in self._COMPL_BY.items()
                     if v == self.compl_by), "By course start"))
        am.pack(side="left")
        bm = ctk.CTkOptionMenu(
            opts, width=140, values=list(self._COMPL_BASIS),
            command=lambda v: self._set_compl_basis(
                self._COMPL_BASIS.get(v, "entry")))
        bm.set(next((k for k, v in self._COMPL_BASIS.items()
                     if v == self.compl_basis), "Entry momentum"))
        bm.pack(side="left", padx=(6, 0))
        ctk.CTkLabel(opts, text="Courses:").pack(side="left", padx=(10, 4))
        codes = history.course_codes()
        if self.courses is None:
            self.courses = set(codes)
        for i, code in enumerate(codes):
            var = ctk.BooleanVar(value=(code in self.courses))
            color = self._course_color(i)
            ctk.CTkCheckBox(
                opts, text=code, variable=var, width=20,
                checkbox_width=15, checkbox_height=15,
                font=ctk.CTkFont(size=11), fg_color=color, hover_color=color,
                command=lambda c=code, vv=var: self._toggle_course(c, vv),
            ).pack(side="left", padx=(0, 6))
        self._build_date_control(opts)

    def _set_compl_by(self, by) -> None:
        self.compl_by = by
        self._compl = None
        self._render_completion()

    def _set_compl_basis(self, basis) -> None:
        self.compl_basis = basis
        self._compl = None
        self._render_completion()

    def _view_completion(self, parent) -> None:
        dark = ctk.get_appearance_mode() == "Dark"
        self.canvas = tk.Canvas(parent, bd=0, highlightthickness=0,
                                bg=("#1d1e1e" if dark else "#f9f9fa"))
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda e: self._on_compl_configure())

    def _on_compl_configure(self) -> None:
        if self.canvas is None or self.canvas.winfo_width() < 120:
            return
        (self._render_completion() if self._compl is None
         else self._draw_completion())

    def _render_completion(self) -> None:
        if self.canvas is None:
            return
        df, dt_ = self._date_bounds()
        self._compl = history.completion_by_month(
            by=self.compl_by, basis=self.compl_basis, courses=self.courses,
            date_from=df, date_to=dt_)
        months = self._compl["months"]
        tot = sum(m["total"] for m in months)
        axis = ("course start (a cohort)" if self.compl_by == "start"
                else "resolution date")
        mom = ("entry" if self.compl_basis == "entry" else "at-outcome")
        self.status.configure(text=(
            f"Completion by month — {tot} students across {len(months)} months, "
            f"bucketed by {axis}. Bars = students that month (left axis, count). "
            "Green = ACTUAL pass rate (passed ÷ resolved); the shaded band = the "
            "WGU Momentum indicator's PREDICTED range — each student's "
            f"{mom} Momentum band (Low 0-20% … High 80-100%), averaged low-to-"
            "high over the month (right axis, %; dashed line = midpoint). Where "
            "actual sits ABOVE the band, students are beating the indicator. "
            "Note: "
            "non-passes only resolve at term end, so actual reads high until "
            "terms close."))
        self._draw_completion()

    def _draw_completion(self) -> None:
        c = self.canvas
        if c is None or not self._compl:
            return
        c.delete("all")
        W, H = c.winfo_width(), c.winfo_height()
        if W < 160 or H < 120:
            return
        dark = ctk.get_appearance_mode() == "Dark"
        fg = "#c0c0c0" if dark else "#444444"
        grid = "#333333" if dark else "#dddddd"
        bg = "#1d1e1e" if dark else "#f9f9fa"
        bar_col = self._blend("#4a9eff", bg, 0.55)
        act_col = "#3fb950"
        pred_col = "#9aa0a6"        # WGU-predicted line (grey, like calibration)
        months = self._compl["months"]
        L, R, T, B = 34, 38, 26, 44
        pw, ph = W - L - R, H - T - B
        if pw < 60 or ph < 50:
            return
        c.create_text(L, 12, anchor="w", fill=fg, font=("", 10, "bold"),
                      text="Completion by month — actual vs momentum estimate")
        if not months:
            c.create_text(W / 2, H / 2, fill=fg,
                          text="No completion data in range yet.")
            return
        maxct = max((m["total"] for m in months), default=1) or 1
        n = len(months)
        slot = pw / n

        def y_ct(v):
            return T + ph * (1 - v / maxct)

        def y_pct(p):
            return T + ph * (1 - p / 100.0)

        for p in (0, 50, 100):                          # right axis = %
            y = y_pct(p)
            c.create_line(L, y, L + pw, y, fill=grid)
            c.create_text(L + pw + 6, y, anchor="w", fill=fg,
                          text=f"{p}%", font=("", 8))
        c.create_text(L - 4, y_ct(maxct), anchor="e", fill=fg,     # left axis
                      text=str(maxct), font=("", 8))
        bw = min(slot * 0.6, 42)
        act_pts, mid_pts = [], []
        hi_pts, lo_pts = [], []            # predicted band upper / lower edges
        for i, m in enumerate(months):
            cx = L + slot * (i + 0.5)
            if m["total"]:
                c.create_rectangle(cx - bw / 2, y_ct(m["total"]),
                                   cx + bw / 2, y_ct(0), fill=bar_col,
                                   outline="")
            if m["actual_rate"] is not None:
                act_pts.append((cx, y_pct(100 * m["actual_rate"])))
            if m.get("predicted_high") is not None:
                hi_pts.append((cx, y_pct(100 * m["predicted_high"])))
                lo_pts.append((cx, y_pct(100 * m["predicted_low"])))
                mid_pts.append((cx, y_pct(100 * m["predicted_rate"])))
            c.create_text(cx, H - B + 12, text=m["month"], fill=fg, font=("", 7))
        # Predicted Momentum band: a see-through shaded range from the mean band
        # LOW bound to the mean HIGH bound, drawn over the bars (stipple lets them
        # show through). Faint dashed center line = the midpoint prediction.
        if len(hi_pts) >= 2:
            poly = [xy for pt in hi_pts for xy in pt]
            poly += [xy for pt in reversed(lo_pts) for xy in pt]
            c.create_polygon(*poly, fill=pred_col, stipple="gray25", outline="")
            c.create_line(*[xy for pt in hi_pts for xy in pt], fill=pred_col,
                          width=1)
            c.create_line(*[xy for pt in lo_pts for xy in pt], fill=pred_col,
                          width=1)
        elif hi_pts:                        # single month → vertical range bar
            (cx, yh), (_, yl) = hi_pts[0], lo_pts[0]
            c.create_rectangle(cx - bw / 2, yh, cx + bw / 2, yl, fill=pred_col,
                               stipple="gray25", outline=pred_col)
        for i in range(len(mid_pts) - 1):               # predicted midpoint
            c.create_line(*mid_pts[i], *mid_pts[i + 1], fill=pred_col, width=1,
                          dash=(4, 3))
        for i in range(len(act_pts) - 1):               # actual: solid green
            c.create_line(*act_pts[i], *act_pts[i + 1], fill=act_col, width=2)
        for cx, cy in act_pts:
            c.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill=act_col,
                          outline="")
        ly = H - 8                                       # legend
        c.create_rectangle(L, ly - 7, L + 12, ly - 1, fill=bar_col, outline="")
        c.create_text(L + 16, ly - 4, anchor="w", fill=fg, font=("", 8),
                      text="students")
        c.create_line(L + 72, ly - 4, L + 94, ly - 4, fill=act_col, width=2)
        c.create_text(L + 98, ly - 4, anchor="w", fill=fg, font=("", 8),
                      text="actual")
        c.create_rectangle(L + 150, ly - 8, L + 172, ly - 1, fill=pred_col,
                           stipple="gray25", outline=pred_col)
        c.create_text(L + 176, ly - 4, anchor="w", fill=fg, font=("", 8),
                      text="predicted band")

    # ---- view: chase list (table) ---------------------------------------
    # The reachable never-attempted students who most need a nudge (FINDINGS
    # §12/§15). Column key matches history.at_risk_students() fields; two display
    # columns ('contact_pref', 'replied') are formatted in _ar_fill.
    _AR_COLS = [
        ("name", "Student", 132, "w"),
        ("student_id", "ID", 76, "center"),
        ("course_code", "Course", 52, "center"),
        ("risk", "Risk", 50, "center"),
        ("avg_momentum_rank", "Avg MI", 54, "center"),
        ("trend", "Trend", 48, "center"),
        ("never_attempted", "Never att", 62, "center"),
        ("days_since_contact", "No contact", 64, "center"),
        ("term_days_left", "Term left", 56, "center"),
        ("reachable", "Reach", 74, "center"),
        ("suggested_channel", "Suggested", 72, "center"),
        ("contact_pref", "Pref", 60, "center"),
        ("ever_responded", "Replied?", 56, "center"),
        ("chase_status", "State", 64, "center"),
    ]
    # Momentum-trajectory window (label -> weeks; None = all history).
    _AR_WINDOWS = {"All history": None, "8 weeks": 8, "6 weeks": 6,
                   "4 weeks": 4}

    def _build_atrisk_controls(self, parent) -> None:
        """Risk-list options: momentum-trajectory WINDOW selector + a 'Show
        dismissed' toggle (dismissed students are hidden by default; on → greyed)."""
        ctk.CTkLabel(parent, text="Window:").pack(side="left", padx=(6, 4))
        cur = next((k for k, v in self._AR_WINDOWS.items()
                    if v == self._ar_window), "All history")
        wm = ctk.CTkOptionMenu(
            parent, width=104, values=list(self._AR_WINDOWS),
            command=self._ar_set_window)
        wm.set(cur)
        wm.pack(side="left", padx=(0, 10))
        self._ar_dismissed_var = tk.BooleanVar(value=self._ar_show_dismissed)
        ctk.CTkCheckBox(
            parent, text="Show dismissed", variable=self._ar_dismissed_var,
            checkbox_width=16, checkbox_height=16, font=ctk.CTkFont(size=11),
            command=self._ar_toggle_dismissed).pack(side="left", padx=(6, 0))

    def _ar_set_window(self, label) -> None:
        self._ar_window = self._AR_WINDOWS.get(label)
        self._ar_refresh()

    def _ar_toggle_dismissed(self) -> None:
        self._ar_show_dismissed = bool(self._ar_dismissed_var.get())
        self._ar_refresh()

    def _view_atrisk(self, parent) -> None:
        self._ar_sort = {"col": None, "rev": False}
        dark = ctk.get_appearance_mode() == "Dark"
        style = ttk.Style()
        style.configure(
            "AtRisk.Treeview", rowheight=22,
            background=("#1d1e1e" if dark else "#ffffff"),
            fieldbackground=("#1d1e1e" if dark else "#ffffff"),
            foreground=("#dce4ee" if dark else "#1a1a1a"))
        tree = ttk.Treeview(parent, style="AtRisk.Treeview", show="headings",
                            columns=[c[0] for c in self._AR_COLS])
        self._ar_tree = tree
        for key, title, w, anchor in self._AR_COLS:
            tree.heading(key, text=title,
                         command=lambda k=key: self._ar_sort_by(k))
            tree.column(key, width=w, anchor=anchor, stretch=(key == "name"))
        # Row colour = risk tier (list is sorted by risk, so this shades the
        # scan): red ≥20% modeled not-pass, amber ≥8%, plain below. Dismissed
        # rows (shown only when the toggle is on) grey out regardless.
        tree.tag_configure("hot", foreground="#e0524f")
        tree.tag_configure("warm", foreground="#d99a2b")
        tree.tag_configure("dismissed", foreground=("#7d7d7d" if dark else "#9a9a9a"))
        tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=sb.set)
        tree.bind("<Double-1>", self._ar_open)
        # Right-click a row → mark contacted / dismiss (snooze) / clear status.
        tree.bind("<Button-3>", self._ar_context_menu)
        self._ar_refresh()

    def _ar_refresh(self) -> None:
        """(Re)load the worklist from the DB (syncing membership) and refill the
        table + status line. Used on first build, after a status change, and on
        the show-dismissed toggle."""
        rows = history.chase_worklist(window_weeks=self._ar_window,
                                      include_dismissed=self._ar_show_dismissed)
        self._ar_rows = rows
        # keep the active sort if one is set
        if self._ar_sort.get("col"):
            self._ar_sort_by(self._ar_sort["col"], _toggle=False)
        else:
            self._ar_fill(rows)
        active = [r for r in rows if r.get("chase_status") != "dismissed"]
        hi = sum(1 for r in active if (r.get("risk") or 0) >= 0.20)
        never = sum(1 for r in active if r.get("never_attempted"))
        contacted = sum(1 for r in active if r.get("chase_status") == "contacted")
        extra = f", {contacted} contacted" if contacted else ""
        win = next((k for k, v in self._AR_WINDOWS.items()
                    if v == self._ar_window), "All history").lower()
        self.status.configure(text=(
            f"{len(active)} in-progress students ranked by not-pass risk from "
            f"their momentum trajectory ({win}); {hi} at ≥20%, {never} never "
            f"attempted a task{extra}. 'Risk' = modeled not-pass probability "
            "(a FLOOR — trust the ordering); 'Avg MI' = mean momentum rank "
            "(1 Low–5 High); 'Trend' ↑ = recovering (deprioritise), ↓ = sliding. "
            "'Never att' is a separate acute flag, not in the score. 'Suggested' "
            "= channel to lead with (* = manual pref). Double-click opens the "
            "student in the viewer; right-click for actions."))

    def _ar_fill(self, rows) -> None:
        t = self._ar_tree
        for i in t.get_children():
            t.delete(i)
        sv = lambda x: "" if x is None else str(x)
        for r in rows:
            st = r.get("chase_status") or ""
            risk = r.get("risk") or 0
            tag = "dismissed" if st == "dismissed" else (
                "hot" if risk >= 0.20 else ("warm" if risk >= 0.08 else ""))
            pref = r.get("contact_pref") or ""
            if pref and r.get("contact_pref_source") == "manual":
                pref += "*"
            tr = r.get("trend") or 0
            trend = "↑" if tr > 0.1 else ("↓" if tr < -0.1 else "→")
            state = {"contacted": "✓ contacted",
                     "dismissed": "dismissed"}.get(st, "")
            t.insert("", "end",
                     iid=f"{r['student_id']}|{r['course_code']}",
                     values=(r["name"], r["student_id"], r["course_code"],
                             f"{round(risk * 100)}%",
                             f"{r.get('avg_momentum_rank', 0):.1f}", trend,
                             "never" if r.get("never_attempted") else "",
                             sv(r.get("days_since_contact")),
                             sv(r["term_days_left"]), r.get("reachable", ""),
                             r.get("suggested_channel", ""), pref,
                             "yes" if r.get("ever_responded") else "never",
                             state),
                     tags=(tag,) if tag else ())

    def _ar_sort_by(self, key, *, _toggle=True) -> None:
        st = self._ar_sort
        if _toggle:
            st["rev"] = (not st["rev"]) if st["col"] == key else False
            st["col"] = key
        field = key

        def sort_key(r):
            v = r.get(field)
            if v is None:
                return (1, "")          # blanks sort last
            if isinstance(v, (int, float)):
                return (0, v)
            return (0, str(v).lower())
        self._ar_rows = sorted(self._ar_rows, key=sort_key, reverse=st["rev"])
        self._ar_fill(self._ar_rows)

    def _ar_open(self, _event=None) -> None:
        """Double-click: pull the student up in the caseload viewer (filtered to
        them), so their info + row actions are right there."""
        r = self._ar_focused_row()
        if r is not None:
            self._ar_show_in_viewer(r)

    def _ar_focused_row(self):
        sel = self._ar_tree.focus()
        if not sel:
            return None
        return next((x for x in self._ar_rows
                     if f"{x['student_id']}|{x['course_code']}" == sel), None)

    def _ar_show_in_viewer(self, r) -> None:
        try:
            self.app.focus_caseload_student(r["student_id"], r.get("name") or "")
        except Exception:
            pass

    def _ar_copy_id(self, r) -> None:
        sid = r["student_id"]
        try:
            self.app.root.clipboard_clear()
            self.app.root.clipboard_append(sid)
            self.app._append_log(f"Copied Student ID: {sid}")
        except Exception:
            pass

    def _ar_context_menu(self, event) -> None:
        """Right-click a chase-list row → mark contacted / dismiss / clear."""
        row = self._ar_tree.identify_row(event.y)
        if not row:
            return
        self._ar_tree.selection_set(row)
        self._ar_tree.focus(row)
        r = next((x for x in self._ar_rows
                  if f"{x['student_id']}|{x['course_code']}" == row), None)
        if r is None:
            return
        cur = r.get("chase_status") or ""
        m = tk.Menu(self._ar_tree, tearoff=0)
        m.add_command(label="👤 Open in viewer",
                      command=lambda: self._ar_show_in_viewer(r))
        m.add_command(label="⧉ Copy Student ID",
                      command=lambda: self._ar_copy_id(r))
        m.add_separator()
        m.add_command(
            label=("✓ Contacted (set)" if cur != "contacted"
                   else "✓ Contacted ✓"),
            command=lambda: self._ar_set_status(r, "contacted"))
        m.add_command(label="🔕 Dismiss (snooze)",
                      command=lambda: self._ar_set_status(r, "dismissed"))
        if cur:
            m.add_separator()
            m.add_command(label="↩ Clear status",
                          command=lambda: self._ar_set_status(r, ""))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _ar_set_status(self, r, status) -> None:
        history.set_chase_status(r["student_id"], r["course_code"], status)
        label = {"contacted": "marked contacted", "dismissed": "dismissed",
                 "": "status cleared"}.get(status, status)
        try:
            self.app._append_log(
                f"Risk list: {r['name'] or r['student_id']} — {label}.")
        except Exception:
            pass
        self._ar_refresh()
