"""Offline demo launcher — run the whole tool with NO Salesforce/Mongoose login.

For contributors: this boots the app against a fully synthetic sample caseload
(see scripts/sample_data.py) in an isolated config dir (`_demo/`), with the
browser automation turned OFF. You get the real viewer, student info view,
Data/Risk views, momentum, contact prefs, pronouns — everything that reads local
data — without any credentials. Browser-only actions (refresh from Salesforce,
firing notes/emails/texts) show a "demo mode" note instead of doing anything.

Usage (from the repo root):
    python -m scripts.demo            # launch (builds sample data on first run)
    python -m scripts.demo --reset    # rebuild the sample data from scratch

Safe to run alongside your real instance: separate config, no global hotkeys,
no browser, never touches your real history.db or Salesforce session.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "_demo"


def main() -> None:
    SANDBOX.mkdir(parents=True, exist_ok=True)
    # MUST be set before importing anything under src/ — src.config computes its
    # paths (and seeds sample scenarios/templates into the sandbox) at import.
    os.environ["CASELOAD_CONFIG_DIR"] = str(SANDBOX)
    os.environ["CASELOAD_OFFLINE"] = "1"
    os.environ["CASELOAD_NO_HOTKEYS"] = "1"
    os.environ["CASELOAD_TITLE_SUFFIX"] = "   ●  OFFLINE DEMO (sample data)"

    # Build the synthetic caseload + history.db into the sandbox on first run
    # (or whenever --reset is passed). Writes caseload.csv + history.db there.
    from scripts import sample_data
    if "--reset" in sys.argv or not (SANDBOX / "history.db").exists():
        summary = sample_data.build(SANDBOX)
        print(f"Built sample data: {summary['live']} live + "
              f"{summary['departed']} departed students, "
              f"{summary['weeks']} weeks of momentum history.")

    from scripts.launcher import main as launcher_main
    launcher_main()


if __name__ == "__main__":
    main()
