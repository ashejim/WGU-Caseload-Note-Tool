"""The Manage-playlists dialog — create / rename / delete queue playlists and
edit each one's ordered list of batch actions.

A playlist is just a name + an ordered list of action names (see
``scenarios.Playlist``). This dialog is a pure editor: it works on a private
copy of the playlists and hands the edited list back through ``on_save`` only
when the user presses Save — the App owns persistence (``_persist_playlists``).

Opened from the Queue tab's "⚙ Manage playlists" button.
"""
from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from src.scenarios import Playlist
from src.ui_common import (
    SECONDARY_BTN_KWARGS, _ADD_BTN_BLUE, _ADD_BTN_BLUE_HOVER, _attach_tooltip,
)


def open_playlist_manager(
    parent,
    playlists: list[Playlist],
    eligible: list[str],
    display_of: dict[str, str],
    status_of: dict[str, str],
    on_save: Callable[[list[Playlist]], None],
) -> None:
    """Pop the modal playlist editor.

    ``playlists``   current playlists (copied — not mutated until Save).
    ``eligible``    action names offered in the "add action" dropdown, in order
                    (queueable batch actions only).
    ``display_of``  action name -> display label (for the ordered rows).
    ``status_of``   action name -> "" if queueable else a short reason
                    ('single-student' / 'branched' / 'text-only'); a name absent
                    from this map is treated as missing/deleted.
    ``on_save``     called with the edited list of Playlist on Save.
    """
    _PlaylistManager(parent, playlists, eligible, display_of, status_of, on_save)


class _PlaylistManager:
    def __init__(self, parent, playlists, eligible, display_of, status_of,
                 on_save) -> None:
        self.on_save = on_save
        self.eligible = list(eligible)
        self.display_of = dict(display_of)
        self.status_of = dict(status_of)
        # Private working copy — edits don't touch the App's list until Save.
        self.working: list[Playlist] = [
            Playlist(name=p.name, actions=list(p.actions)) for p in playlists
        ]
        self.selected: Optional[int] = 0 if self.working else None

        self.dialog = ctk.CTkToplevel(parent)
        self.dialog.title("Manage playlists")
        self.dialog.geometry("760x520")
        self.dialog.transient(parent)
        self.dialog.attributes("-topmost", True)
        self.dialog.grab_set()
        self.dialog.grid_columnconfigure(0, weight=0, minsize=220)
        self.dialog.grid_columnconfigure(1, weight=1)
        self.dialog.grid_rowconfigure(0, weight=1)

        # ---- left: playlist list + New/Rename/Delete --------------------
        left = ctk.CTkFrame(self.dialog)
        left.grid(row=0, column=0, sticky="nsew", padx=(10, 4), pady=10)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(left, text="Playlists",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, sticky="w", padx=8, pady=(8, 4))
        self.pl_list = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.pl_list.grid(row=1, column=0, sticky="nsew", padx=4)
        self.pl_list.grid_columnconfigure(0, weight=1)
        btnrow = ctk.CTkFrame(left, fg_color="transparent")
        btnrow.grid(row=2, column=0, sticky="ew", padx=4, pady=(6, 8))
        ctk.CTkButton(btnrow, text="＋ New", width=64,
                      command=self._new_playlist).pack(side="left")
        ctk.CTkButton(btnrow, text="Rename", width=64, command=self._rename,
                      **SECONDARY_BTN_KWARGS).pack(side="left", padx=4)
        ctk.CTkButton(btnrow, text="🗑 Delete", width=72, command=self._delete,
                      **SECONDARY_BTN_KWARGS).pack(side="left")

        # ---- right: selected playlist's ordered actions -----------------
        right = ctk.CTkFrame(self.dialog)
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 10), pady=10)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)
        self.right_head = ctk.CTkLabel(
            right, text="Actions (run in this order)",
            font=ctk.CTkFont(weight="bold"))
        self.right_head.grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))
        self.rows = ctk.CTkScrollableFrame(right, fg_color="transparent")
        self.rows.grid(row=1, column=0, sticky="nsew", padx=4)
        self.rows.grid_columnconfigure(0, weight=1)

        addrow = ctk.CTkFrame(right, fg_color="transparent")
        addrow.grid(row=2, column=0, sticky="ew", padx=4, pady=(6, 8))
        self.add_var = ctk.StringVar(value="")
        self.add_menu = ctk.CTkOptionMenu(
            addrow, variable=self.add_var, values=["(no actions)"], width=280)
        self.add_menu.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(addrow, text="Add action", width=90,
                      command=self._add_action).pack(side="left", padx=(6, 0))

        # ---- bottom: Save / Cancel --------------------------------------
        bottom = ctk.CTkFrame(self.dialog, fg_color="transparent")
        bottom.grid(row=1, column=0, columnspan=2, sticky="e",
                    padx=10, pady=(0, 10))
        ctk.CTkButton(bottom, text="Cancel", width=90, command=self._cancel,
                      **SECONDARY_BTN_KWARGS).pack(side="right")
        ctk.CTkButton(
            bottom, text="Save", width=90, command=self._save,
            fg_color=_ADD_BTN_BLUE, hover_color=_ADD_BTN_BLUE_HOVER,
        ).pack(side="right", padx=(0, 8))

        self._render()

    # ---- rendering -------------------------------------------------------
    def _render(self) -> None:
        self._render_left()
        self._render_right()

    def _render_left(self) -> None:
        for w in self.pl_list.winfo_children():
            w.destroy()
        if not self.working:
            ctk.CTkLabel(self.pl_list, text="No playlists yet.\nPress ＋ New.",
                         justify="left",
                         text_color=("gray45", "gray60")).grid(
                row=0, column=0, sticky="w", padx=8, pady=10)
            return
        for i, p in enumerate(self.working):
            sel = (i == self.selected)
            b = ctk.CTkButton(
                self.pl_list,
                text=f"{p.name}  ({len(p.actions)})",
                anchor="w", height=30,
                fg_color=(("#2f6fed", "#2f6fed") if sel
                          else ("gray85", "gray25")),
                text_color=(("white", "white") if sel else ("gray10", "gray90")),
                hover_color=("#2558c8", "#2558c8") if sel else ("gray75", "gray32"),
                command=lambda n=i: self._select(n),
            )
            b.grid(row=i, column=0, sticky="ew", padx=4, pady=2)

    def _render_right(self) -> None:
        for w in self.rows.winfo_children():
            w.destroy()
        p = self._current()
        if p is None:
            self.right_head.configure(text="Actions (run in this order)")
            ctk.CTkLabel(
                self.rows,
                text="Select or create a playlist to edit its actions.",
                text_color=("gray45", "gray60")).grid(
                row=0, column=0, sticky="w", padx=8, pady=10)
            self._refresh_add_menu()
            return
        self.right_head.configure(text=f"“{p.name}” — actions (run in order)")
        if not p.actions:
            ctk.CTkLabel(
                self.rows,
                text=("No actions in this playlist.\nPick one below and press "
                      "“Add action”."),
                justify="left", text_color=("gray45", "gray60")).grid(
                row=0, column=0, sticky="w", padx=8, pady=10)
        else:
            for i, aname in enumerate(p.actions):
                self._render_action_row(i, aname, len(p.actions))
        self._refresh_add_menu()

    def _render_action_row(self, i: int, aname: str, total: int) -> None:
        frame = ctk.CTkFrame(self.rows, fg_color=("gray92", "gray17"))
        frame.grid(row=i, column=0, sticky="ew", pady=2)
        frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(frame, text=f"{i + 1}.", width=26,
                     text_color=("gray40", "gray60")).grid(
            row=0, column=0, padx=(8, 2), pady=6)
        # Label + a warning suffix if the action is missing or not queueable.
        label = self.display_of.get(aname, aname)
        reason = self._reason(aname)
        warn = None
        if reason == "missing":
            warn = "⚠ no longer exists — will be skipped"
        elif reason:
            warn = f"⚠ {reason} — will be skipped"
        lbl = ctk.CTkLabel(frame, text=label, anchor="w")
        if warn:
            lbl.configure(text_color=("#c0392b", "#e0524f"))
        lbl.grid(row=0, column=1, sticky="ew", padx=2)
        if warn:
            wl = ctk.CTkLabel(frame, text=warn, anchor="e",
                              text_color=("#c0392b", "#e0524f"),
                              font=ctk.CTkFont(size=11))
            wl.grid(row=0, column=2, padx=(2, 4))
        up = ctk.CTkButton(frame, text="↑", width=28, height=24,
                           command=lambda n=i: self._move(n, -1),
                           **SECONDARY_BTN_KWARGS)
        up.grid(row=0, column=3, padx=1)
        if i == 0:
            up.configure(state="disabled")
        dn = ctk.CTkButton(frame, text="↓", width=28, height=24,
                           command=lambda n=i: self._move(n, +1),
                           **SECONDARY_BTN_KWARGS)
        dn.grid(row=0, column=4, padx=1)
        if i == total - 1:
            dn.configure(state="disabled")
        rm = ctk.CTkButton(frame, text="✕", width=28, height=24,
                           command=lambda n=i: self._remove_action(n),
                           **SECONDARY_BTN_KWARGS)
        rm.grid(row=0, column=5, padx=(1, 8))

    def _refresh_add_menu(self) -> None:
        """Offer eligible actions not already in the current playlist."""
        p = self._current()
        in_pl = set(p.actions) if p else set()
        choices = [self.display_of.get(n, n)
                   for n in self.eligible if n not in in_pl]
        self._display_to_name = {
            self.display_of.get(n, n): n
            for n in self.eligible if n not in in_pl
        }
        if p is None:
            choices = []
        if choices:
            self.add_menu.configure(values=choices, state="normal")
            if self.add_var.get() not in choices:
                self.add_var.set(choices[0])
        else:
            placeholder = ("(all eligible actions already added)" if p is not None
                           else "(select a playlist)")
            self.add_menu.configure(values=[placeholder], state="disabled")
            self.add_var.set(placeholder)

    # ---- helpers ---------------------------------------------------------
    def _current(self) -> Optional[Playlist]:
        if self.selected is None or not (0 <= self.selected < len(self.working)):
            return None
        return self.working[self.selected]

    def _reason(self, aname: str) -> str:
        """'' if queueable, 'missing' if the action is gone, else the reason."""
        if aname not in self.status_of and aname not in self.display_of:
            return "missing"
        return self.status_of.get(aname, "")

    def _unique_name(self, base: str) -> str:
        names = {p.name for p in self.working}
        if base not in names:
            return base
        i = 2
        while f"{base} {i}" in names:
            i += 1
        return f"{base} {i}"

    # ---- actions ---------------------------------------------------------
    def _select(self, idx: int) -> None:
        self.selected = idx
        self._render()

    def _new_playlist(self) -> None:
        name = self._prompt_name("New playlist", "Playlist name:", "")
        if not name:
            return
        if any(p.name == name for p in self.working):
            self._warn(f"A playlist named “{name}” already exists.")
            return
        self.working.append(Playlist(name=name, actions=[]))
        self.selected = len(self.working) - 1
        self._render()

    def _rename(self) -> None:
        p = self._current()
        if p is None:
            return
        name = self._prompt_name("Rename playlist", "New name:", p.name)
        if not name or name == p.name:
            return
        if any(q is not p and q.name == name for q in self.working):
            self._warn(f"A playlist named “{name}” already exists.")
            return
        p.name = name
        self._render()

    def _delete(self) -> None:
        p = self._current()
        if p is None:
            return
        from tkinter import messagebox
        if not messagebox.askyesno(
                "Delete playlist",
                f"Delete the playlist “{p.name}”?\n\n"
                "This removes the playlist only — the actions themselves are "
                "untouched.", parent=self.dialog):
            return
        del self.working[self.selected]
        if not self.working:
            self.selected = None
        else:
            self.selected = max(0, self.selected - 1)
        self._render()

    def _add_action(self) -> None:
        p = self._current()
        if p is None:
            return
        name = getattr(self, "_display_to_name", {}).get(self.add_var.get())
        if not name:
            return
        if name not in p.actions:
            p.actions.append(name)
        self._render()

    def _remove_action(self, idx: int) -> None:
        p = self._current()
        if p is None or not (0 <= idx < len(p.actions)):
            return
        del p.actions[idx]
        self._render()

    def _move(self, idx: int, delta: int) -> None:
        p = self._current()
        if p is None:
            return
        j = idx + delta
        if not (0 <= j < len(p.actions)):
            return
        p.actions[idx], p.actions[j] = p.actions[j], p.actions[idx]
        self._render()

    def _save(self) -> None:
        # Drop nameless playlists defensively (shouldn't happen — creation
        # requires a name), then hand the edited list to the App.
        out = [p for p in self.working if p.name.strip()]
        self._close()
        try:
            self.on_save(out)
        except Exception:
            pass

    def _cancel(self) -> None:
        self._close()

    def _close(self) -> None:
        try:
            self.dialog.grab_release()
        except Exception:
            pass
        try:
            self.dialog.destroy()
        except Exception:
            pass

    # ---- tiny modal helpers (kept local so this module stays standalone) --
    def _prompt_name(self, title: str, label: str, initial: str) -> str:
        top = ctk.CTkToplevel(self.dialog)
        top.title(title)
        top.geometry("380x150")
        top.transient(self.dialog)
        top.attributes("-topmost", True)
        top.grab_set()
        ctk.CTkLabel(top, text=label).pack(padx=16, pady=(16, 4), anchor="w")
        var = ctk.StringVar(value=initial)
        entry = ctk.CTkEntry(top, textvariable=var, width=340)
        entry.pack(padx=16)
        entry.focus_set()
        entry.icursor("end")
        result = {"value": ""}

        def ok(_e=None):
            result["value"] = var.get().strip()
            _destroy()

        def cancel(_e=None):
            result["value"] = ""
            _destroy()

        def _destroy():
            try:
                top.grab_release()
            except Exception:
                pass
            top.destroy()

        row = ctk.CTkFrame(top, fg_color="transparent")
        row.pack(pady=14)
        ctk.CTkButton(row, text="Cancel", width=80, command=cancel,
                      **SECONDARY_BTN_KWARGS).pack(side="right", padx=(6, 0))
        ctk.CTkButton(row, text="OK", width=80, command=ok).pack(side="right")
        top.bind("<Return>", ok)
        top.bind("<Escape>", cancel)
        self.dialog.wait_window(top)
        # The nested prompt stole the grab; take it back so the manager stays
        # modal after the prompt closes.
        try:
            self.dialog.grab_set()
        except Exception:
            pass
        return result["value"]

    def _warn(self, msg: str) -> None:
        from tkinter import messagebox
        messagebox.showwarning("Playlists", msg, parent=self.dialog)
