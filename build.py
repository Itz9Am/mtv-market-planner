#!/usr/bin/env python3
"""Inject tents.json into planner.template.html -> marknad_tent_planner.html

The template contains the literal placeholder __TENTS_JSON__ inside its <script> block.
Run after any edit to the template or the data.

    python3 build.py

All files live flat in the repo root (template, data, and generated artifact together).
"""
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
TEMPLATE = ROOT / "planner.template.html"
DATA = ROOT / "tents.json"
OUT = ROOT / "marknad_tent_planner.html"
PLACEHOLDER = "__TENTS_JSON__"


def main() -> int:
    html = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        print(f"ERROR: {PLACEHOLDER} not found in template", file=sys.stderr)
        return 1

    tents = json.loads(DATA.read_text(encoding="utf-8"))
    html = html.replace(PLACEHOLDER, json.dumps(tents, ensure_ascii=False))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")

    # --- checks -------------------------------------------------------
    script = html.split("<script>")[-1].split("</script>")[0]

    # 1. JS must parse. node is optional but strongly preferred.
    try:
        tmp = ROOT / ".check.js"
        tmp.write_text(script, encoding="utf-8")
        r = subprocess.run(["node", "--check", str(tmp)],
                           capture_output=True, text=True)
        tmp.unlink(missing_ok=True)
        if r.returncode != 0:
            print("SYNTAX ERROR:\n" + r.stderr, file=sys.stderr)
            return 1
        print("syntax OK")
    except FileNotFoundError:
        print("WARNING: node not found, skipped syntax check")

    # 2. No colour emoji anywhere (product requirement). Monochrome UI glyphs
    #    used deliberately on the rotate/delete buttons are allowed.
    ALLOWED_GLYPHS = {"\u2715", "\u21ba", "\u21bb", "\u2716"}
    emoji = sorted(set(re.findall(
        r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF]", html)) - ALLOWED_GLYPHS)
    if emoji:
        print(f"WARNING: emoji found in output: {emoji}", file=sys.stderr)

    # 3. Duplicate ids break place-once tracking and live re-linking.
    ids = [t["id"] for t in tents]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        print(f"WARNING: duplicate tent ids: {sorted(dupes)}", file=sys.stderr)

    print(f"built {OUT.relative_to(ROOT)}  "
          f"({len(html)/1024:.1f} KB, {len(tents)} tents)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
