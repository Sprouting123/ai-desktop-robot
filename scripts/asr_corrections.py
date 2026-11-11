#!/usr/bin/env python3
"""Small, explicit ASR corrections for this robot's domain vocabulary.

SenseVoice (and Paraformer) consistently confuse a few names in the accepted
recordings: "小桌" -> "小卓" and "桌宠" -> "捉宠". SenseVoice has no system
prompt or hotword list, so the receiver applies these exact-substring rules
after ASR and logs every change. Rules must stay few and unambiguous; this is
not a general spell checker and must not rewrite arbitrary user text.

Examples:
    from asr_corrections import correct
    correct("小卓你好")  -> ("小桌你好", ["小卓->小桌"])
"""

from __future__ import annotations

# Applied in order, once each. Add a rule only with a recorded failure case.
RULES = (
    ("小卓", "小桌"),
    ("捉宠", "桌宠"),
)


def correct(text):
    """Return (corrected_text, [rule strings]); never raises on empty input."""
    value = text or ""
    changes = []
    for wrong, right in RULES:
        if wrong in value:
            value = value.replace(wrong, right)
            changes.append(f"{wrong}->{right}")
    return value, changes
