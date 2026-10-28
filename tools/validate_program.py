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
    "sit_up", "deadlift", "good_morning", "pendlay_row", "bb_row",
    # back_squat разрешён с дня 22 (осевая нагрузка): суставы в порядке, работа в раме с упорами
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


def check_grip_streak(days: dict, errors: list[str]) -> None:
    """Fingers and forearms need a day off: no more than two grip days in a row."""
    streak = 0
    for i in range(1, 101):
        has_grip = any("хват" in b["label"].lower() for b in days[str(i)]["payload"]["blocks"])
        streak = streak + 1 if has_grip else 0
        if streak > 2:
            errors.append(f"day {i}: grip block on {streak} consecutive days")


# Mirrors TITLES in build_program.py on purpose: the validator checks the result,
# not the generator's internals. A bench day labelled «Бассейн» is exactly the
# drift that made the app show one thing while another was trained.
TITLES = {"bench_heavy": "Верх · толчок", "bench_volume": "Жим · объём", "pull": "Верх · тяга",
          "legs": "Ноги · квадрицепс", "legs_b": "Ноги · задняя цепь",
          "light": "Кардио · бег", "light2": "Восстановление", "test": "Контрольный день"}


def check_titles(days: dict, errors: list[str]) -> None:
    for i in range(16, 101):
        day = days[str(i)]
        want = "Финал · максимум" if i == 100 else \
            ("Ноги · присед" if day["day_type"] == "legs" and i >= 23 else TITLES.get(day["day_type"]))
        if want and not day["title"].startswith(want):
            errors.append(f"day {i}: title «{day['title']}» does not match day_type {day['day_type']}")


BICEPS = {"incline_curl", "hammer_curl", "cable_curl", "db_curl", "bb_curl",
          "preacher_curl", "concentration_curl", "reverse_curl"}
TRICEPS = {"db_overhead_extension", "rope_overhead_extension", "rope_pushdown",
           "tricep_pushdown", "close_grip_bench"}
SETS_RE = re.compile(r"^\s*(\d+)\s*×")
MAIN_MOVES = {"bb_bench_press", "back_squat", "rdl_bb", "close_grip_bench",
              "leg_press", "hack_squat", "lat_pulldown_neutral", "seated_row"}


def check_arm_volume(days: dict, errors: list[str]) -> None:
    """Руки — заявленный приоритет: 10–18 рабочих подходов в неделю на бицепс и
    на трицепс. Ниже — не вырастут, выше — не восстановятся при двух днях жима.
    Контрольные и разгрузочные недели считаются отдельно и не проверяются."""
    for start in range(29, 95, 7):
        week = [days[str(i)] for i in range(start, start + 7)]
        if any(d["day_type"] == "test" or "разгрузка" in d["title"] for d in week):
            continue
        counts = {"biceps": 0, "triceps": 0}
        for day in week:
            for b in day["payload"]["blocks"]:
                for item in b["items"]:
                    m = SETS_RE.match(item["text"])
                    n = int(m.group(1)) if m else 0
                    if item["movement"] in BICEPS:
                        counts["biceps"] += n
                    if item["movement"] in TRICEPS:
                        counts["triceps"] += n
        for name, n in sorted(counts.items()):
            if not 10 <= n <= 18:
                errors.append(f"days {start}-{start + 6}: {n} {name} sets, outside the 10-18 corridor")


def check_bonus_blocks(days: dict, errors: list[str]) -> None:
    """Бонусный блок не держит день, поэтому главное движение в нём — потеря работы."""
    for key in sorted(days, key=int):
        blocks = days[key]["payload"]["blocks"]
        if not any(not b.get("optional") for b in blocks):
            errors.append(f"day {key}: every block is a bonus, the day can never be required")
        for b in blocks:
            if not b.get("optional"):
                continue
            for item in b["items"]:
                if item["movement"] in MAIN_MOVES:
                    errors.append(f"day {key}: main lift {item['movement']} sits in bonus block «{b['label']}»")


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    days, moves = data["days"], data["moves"]
    if sorted(days, key=int) != [str(i) for i in range(1, 101)]:
        errors.append("days must be exactly 1..100")
    for key in sorted(days, key=int):
        check_day(key, days[key], moves, errors)
    check_media(days, moves, errors)
    check_grip_streak(days, errors)
    check_titles(days, errors)
    check_arm_volume(days, errors)
    check_bonus_blocks(days, errors)
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
