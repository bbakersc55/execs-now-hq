"""2026-10-03: the platform owner's area switch was hidden under the New note
button. The sidebar is a full-height flex column; a brand block allowed to
shrink let its content run under the button. The frontend test checks the
switch's place in the DOM; this checks the rule that keeps the blocks from
shrinking, which the frontend test runner cannot read (it strips CSS)."""

import pathlib
import re

CSS = (pathlib.Path(__file__).resolve().parent.parent / "frontend/src/theme.css").read_text()


def test_the_top_of_the_sidebar_never_shrinks():
    rule = re.search(r"^([^\n{}/*]+)\{\s*flex-shrink:\s*0;\s*\}", CSS, re.M)
    selectors = {s.strip() for s in rule.group(1).split(",")}
    assert {".sidebar .brand", ".sidebar .area-switch", ".sidebar .capture-trigger"} <= selectors


def test_the_switch_has_its_own_spacing():
    assert re.search(r"\.sidebar \.area-switch \{ display: block; margin: [^;]+; \}", CSS)
