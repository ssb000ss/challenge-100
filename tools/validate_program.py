#!/usr/bin/env python3
"""Check data.json against hardware and health constraints from CLAUDE.md.

Exit code 1 and a list of violations if anything is off.
Usage: python3 tools/validate_program.py [path/to/data.json]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data.json"
KG_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*кг")
KETTLEBELLS = {8, 12, 16, 20, 24, 28, 32}

# Contraindicated for the owner's joints and spine (details kept out of the repo),
# plus kit the gym doesn't have.
BANNED = {
    "upright_row", "bench_dip", "bar_dip", "push_up_deficit", "cuban_press",
    "kb_overhead_hold", "waiter_walk", "overhead_carry", "push_jerk", "push_press",
    "bb_strict_press", "bb_seated_press",
    "curtsy_lunge", "deep_squat_hold", "box_jump", "jump_squat", "broad_jump", "burpee",
    "sit_up", "deadlift", "good_morning", "pendlay_row", "bb_row", "back_squat",
    "hanging_leg_raise", "toes_to_bar", "kipping_pull_up",
    "row_erg",
    # not in this gym: no elliptical (day 5 note), and the cable stack cannot be
    # set low enough for external rotation — it runs on a band instead
    "elliptical", "cable_external_rotation",
}


def step_for(move: dict, code: str) -> tuple[str, set[float] | float | None]:
    eq = move.get("equipment", "")
    if code in ("inverted_row", "landmine_shoulder_press") or "гравитрон" in eq:
        return "skip", None
    if "штанга" in eq:
        return "barbell", 10.0
    if "гир" in eq:
        return "kettlebell", KETTLEBELLS
    if "гантел" in eq:
        return "dumbbell", 2.5
    if "блин" in eq:
        return "plate", 5.0
    return "machine", 2.5


def check_item(day: str, part: str, item: dict, moves: dict, errors: list[str]) -> None:
    code = item["movement"]
    where = f"day {day} {part} {code}"
    if code not in moves:
        errors.append(f"{where}: unknown movement")
        return
    if code in BANNED:
        errors.append(f"{where}: contraindicated or unavailable")
    if (moves[code].get("unlock_day") or 1) > int(day):
        errors.append(f"{where}: used before unlock_day {moves[code]['unlock_day']}")
    kind, rule = step_for(moves[code], code)
    for raw in KG_RE.findall(item["text"]):
        value = float(raw.replace(",", "."))
        if kind == "kettlebell" and value not in rule:
            errors.append(f"{where}: kettlebell {value:g} not in standard series")
        elif isinstance(rule, float) and value % rule:
            errors.append(f"{where}: {kind} {value:g} kg is not a multiple of {rule:g}")


def check_day(key: str, day: dict, moves: dict, errors: list[str]) -> None:
    for part in ("payload", "variant"):
        for b in day[part].get("blocks", []):
            for item in b["items"]:
                check_item(key, part, item, moves, errors)
    blocks = day["payload"]["blocks"]
    seen: dict[str, str] = {}
    for b in blocks:
        for item in b["items"]:
            code = item["movement"]
            if code in seen:
                errors.append(f"day {key}: {code} repeats in «{seen[code]}» and «{b['label']}»")
            seen.setdefault(code, b["label"])
    presses = any(i["movement"] == "bb_bench_press" for b in blocks for i in b["items"])
    has_shoulder = any("плеч" in b["label"].lower() for b in blocks)
    if presses and not has_shoulder:
        errors.append(f"day {key}: bench day without shoulder-protection block")
    if not blocks:
        errors.append(f"day {key}: empty payload")


def check_media(days: dict, moves: dict, errors: list[str]) -> None:
    used = {i["movement"] for d in days.values() for part in ("payload", "variant")
            for b in d[part].get("blocks", []) for i in b["items"]}
    for code in sorted(used & moves.keys()):
        if not moves[code].get("steps"):
            errors.append(f"move {code}: no Russian technique steps")
        for img in moves[code].get("images", []):
            if not (DEFAULT_PATH.parent / img).is_file():
                errors.append(f"move {code}: missing image {img}")


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    days, moves = data["days"], data["moves"]
    if sorted(days, key=int) != [str(i) for i in range(1, 101)]:
        errors.append("days must be exactly 1..100")
    for key in sorted(days, key=int):
        check_day(key, days[key], moves, errors)
    check_media(days, moves, errors)
    return errors


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    errors = validate(json.loads(path.read_text(encoding="utf-8")))
    for e in errors:
        print(e)
    print(f"{len(errors)} violation(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
