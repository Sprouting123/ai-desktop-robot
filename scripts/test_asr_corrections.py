#!/usr/bin/env python3
"""Tests for scripts/asr_corrections.py (no network, no model)."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from asr_corrections import RULES, correct  # noqa: E402

failures = 0
checks = 0


def check(name, actual, expected):
    global failures, checks
    checks += 1
    if actual == expected:
        print(f"  ok   {name}: {actual}")
    else:
        failures += 1
        print(f"  FAIL {name}: expected {expected!r}, got {actual!r}")


check("no_change", correct("今天天气怎么样"),
      ("今天天气怎么样", []))
check("xiaozhuo", correct("小卓你好"), ("小桌你好", ["小卓->小桌"]))
check("zhuochong", correct("你是捉宠吗"), ("你是桌宠吗", ["捉宠->桌宠"]))
check("both", correct("小卓是捉宠"), ("小桌是桌宠",
                                    ["小卓->小桌", "捉宠->桌宠"]))
check("repeat", correct("小卓小卓"), ("小桌小桌", ["小卓->小桌"]))
check("already_right", correct("小桌和桌宠"), ("小桌和桌宠", []))
check("empty", correct(""), ("", []))
check("none", correct(None), ("", []))
check("unrelated_zhuo", correct("卓越"), ("卓越", []))
check("unrelated_chong", correct("宠物"), ("宠物", []))
check("rules_size", len(RULES), 2)
check("rules_types", all(len(rule) == 2 and rule[0] and rule[1]
                         for rule in RULES), True)

print()
print(f"{'PASS' if failures == 0 else 'FAIL'}: {checks - failures}/"
      f"{checks} checks passed")
sys.exit(0 if failures == 0 else 1)
