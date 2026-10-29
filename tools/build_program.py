#!/usr/bin/env python3
"""Rebuild the 100-day program in data.json.

Principles baked in (see CLAUDE.md):
- Main goal is overall shape and conditioning; bench is the headline metric.
- Barbell loads are multiples of 10 kg (20 kg bar, 5 kg smallest plate).
- Dumbbells follow the standard 2.5 kg rack, kettlebells the 4 kg series.
- Main lifts stay fixed within a 28-day block; progression goes through
  reps/sets inside a block and through load between blocks.
- Every pressing day carries the mandatory shoulder-protection block.
- Health: no loaded spinal flexion, nothing overhead with a barbell/kettlebell.
  Knees and shoulders are healthy (owner confirmed on day 6), so squat depth
  and pulling volume are no longer capped for joint protection.
- Loads follow reported reality: the owner logs actual weights in day notes,
  and the tables below are corrected from those logs, not from guesses.

Days 1-6 are kept (already closed): log indices map to items by position,
so closed days must keep their item count and order untouched.
No movement repeats within a day; warm-up ramps live in the main item note.
Only days[N].payload/title and moves are touched; state and logs are not.
Usage: python3 tools/build_program.py [path/to/data.json]
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "data.json"
IMAGES_MAP = Path(__file__).resolve().parent / "exercise_images.json"
STEPS_RU = Path(__file__).resolve().parent / "exercise_steps_ru.json"
KEEP_DAYS = {1, 2, 3, 4, 5, 6}  # closed days: logs store checked item indices
DELOAD_WEEK = 3  # 4th week of blocks 2 and 3
TAPER_FROM = 93  # last week before the final test

# Возврат после перерыва (болезнь 05.10–15.10): первые четыре сессии идут ниже плана.
# Ключ — номер дня, "subs" заменяет текст упражнения, не трогая структуру дня.
# Возврат после паузы: скидка к плановым весам на первые сессии.
# Пусто — владелец вернулся на плановые веса с дня 18, «продолжаем где остановился».
# Механизм остаётся для следующей паузы: {день: ("пометка", {движение: "новый текст"})}.
RE_ENTRY: dict[int, tuple[str, dict[str, str]]] = {}


def apply_re_entry(d: int, payload: dict) -> dict:
    """Scale the first sessions after the illness pause down, keeping the day intact."""
    if d not in RE_ENTRY:
        return payload
    note, subs = RE_ENTRY[d]
    for block in payload["blocks"]:
        for item in block["items"]:
            if item["movement"] in subs:
                item["text"] = subs.pop(item["movement"])
    bench = next((i["text"] for bl in payload["blocks"] for i in bl["items"] if i["movement"] == "bb_bench_press"), None)
    payload["subtitle"] = "Возврат после болезни." + (f" Жим {bench}." if bench else "")
    payload["rules"] = f"Возврат: {note} · " + payload["rules"]
    return payload

NEW_MOVES = {
    "band_external_rotation": {
        "name_ru": "Наружная ротация с резиной",
        "cue": "Резина закреплена на уровне локтя, локоть прижат к корпусу. Поворачивай предплечье наружу, 2 секунды обратно. Натяжение такое, чтобы последние повторы были заметны, но лёгкими.",
        "equipment": "резина", "category": "shoulder", "unit": "повт",
    },
    "air_bike": {
        "name_ru": "Велотренажёр с ручками",
        "cue": "Работают и ноги, и руки. Спина прямая, корпус не раскачивается. На интервалах держи темп руками — пульс поднимается быстрее.",
        "equipment": "велотренажёр с ручками", "category": "cardio", "unit": "мин",
    },
    "swim_kick_board": {
        "name_ru": "Ноги с доской",
        "cue": "Доска в вытянутых руках, работают только ноги от бедра. Лицо в воде, выдох в воду, вдох поворотом головы в сторону. Широчайшие отдыхают — в этом весь смысл.",
        "equipment": "бассейн, доска", "category": "cardio", "unit": "м",
    },
    "swim_breathing": {
        "name_ru": "Дыхание у бортика",
        "cue": "Держишься за бортик, лицо в воду — выдох в воду до конца, поворот головы в сторону — вдох. Выдыхай полностью, тогда вдох получается сам.",
        "equipment": "бассейн", "category": "cardio", "unit": "повт",
    },
    "dead_bug": {
        "name_ru": "Мёртвый жук",
        "cue": "Поясница прижата к полу всё время. Противоположные рука и нога медленно уходят от корпуса на выдохе. Если поясница отрывается — амплитуду меньше.",
        "equipment": "—", "category": "core", "unit": "повт",
    },
    "bird_dog": {
        "name_ru": "Птица-собака",
        "cue": "На четвереньках, спина ровная. Вытяни противоположные руку и ногу, задержи 2 секунды. Таз не заваливается, поясница не прогибается.",
        "equipment": "—", "category": "core", "unit": "повт",
    },
    "close_grip_bench": {
        "name_ru": "Жим штанги узким хватом",
        "cue": "Хват чуть уже плеч, локти вдоль корпуса под 30–45°. Штанга касается низа груди. Главный помощник жима — трицепс в дожиме.",
        "equipment": "штанга, скамья", "category": "push", "unit": "повт",
    },
    "elliptical": {
        "name_ru": "Эллипсоид",
        "cue": "Спина прямая, давишь педали всей стопой, руки работают активно. На интервалах — темп, но без рывков.",
        "equipment": "эллипсоид", "category": "cardio", "unit": "мин",
    },
    "glute_bridge": {
        "name_ru": "Ягодичный мостик",
        "cue": "Лёжа на спине, стопы у таза. Подними таз за счёт ягодиц, вверху пауза 1 секунда. Поясницу не прогибать.",
        "equipment": "—", "category": "hinge", "unit": "повт",
    },
    "db_overhead_extension": {
        "name_ru": "Французский жим с гантелью из-за головы",
        "cue": "Одна гантель в двух руках над головой, локти смотрят вперёд и стоят на месте. Опускай за голову до полного растяжения, разгибай без рывка. Длинная головка трицепса — самая крупная из трёх и растёт именно из этого положения.",
        "equipment": "гантель, скамья", "category": "push", "unit": "повт",
    },
    "rope_overhead_extension": {
        "name_ru": "Разгибания с канатом из-за головы",
        "cue": "Канат из нижнего блока, стоишь спиной к стойке, корпус в наклоне. Локти у головы, разгибай вперёд-вверх. Натяжение в трицепсе есть и в растянутом положении — в этом вся разница с разгибаниями вниз.",
        "equipment": "блок", "category": "push", "unit": "повт",
    },
    "cat_camel": {
        "name_ru": "Кошка-верблюд",
        "cue": "На четвереньках медленно округляй и прогибай спину в комфортной амплитуде. Не растяжка, а разминка для позвоночника — без усилия.",
        "equipment": "—", "category": "mob", "unit": "повт",
    },
}

# ---------- helpers ----------
# Cable external rotation is unusable on the owner's stack (day 5 note), so the
# rotation runs on a band; the level steps up with the block.
ER_BAND = {1: "лёгкая", 2: "лёгкая", 3: "средняя", 4: "средняя"}
# Progression rule shown on main lifts so the weekly step is explicit.
STEP_UP = "все повторы чисто и RPE ≤ 8 — в следующий раз +5 кг (тренажёр) или +2.5 кг (гантели) · рабочий вес пиши в заметку"


def kg(x: float) -> str:
    return f"{x:g}"


def it(movement: str, text: str, note: str | None = None) -> dict:
    item = {"movement": movement, "text": text}
    if note:
        item["note"] = note
    return item


def blk(label: str, items: list[dict], note: str | None = None) -> dict:
    block = {"label": label, "items": items}
    if note:
        block["note"] = note
    return block


def water(d: int) -> str:
    week = (d - 1) // 7 + 1
    return "2 л" if week <= 2 else ("2,5 л" if week <= 4 else "3 л")


def rules(d: int, strength: bool) -> str:
    base = f"Шаги 8–10 тыс. · вода {water(d)} · сон 7+ · алкоголь нет · белок в каждый приём пищи"
    return ("RPE ≤ 8: 2 повтора в запасе, отказ запрещён · " + base) if strength else base


def pick(seq: list, i: int):
    return seq[min(i, len(seq) - 1)]


# Cardio is prescribed in distance, not minutes: a kilometre is a task you can
# finish, a minute is a timer you can coast through.
BIKE_KM = {3: 1, 5: 1.5, 6: 2}          # warm-up ride, by the minutes it replaces
WALK_KM = {1: 3, 2: 3.5, 3: 4, 4: 4}    # brisk walk on the light day, by block
RECOVERY_KM = {1: 5, 2: 7, 3: 7, 4: 7}  # easy spin on the recovery day, by block
WALK_PACE = "бодрый темп, 9–10 минут на километр — дышишь, но можешь говорить"
# Running opens up because the knee is healthy (owner confirmed on day 6). It
# grows from walk/run intervals to a continuous 3 km, by light-day number.
RUN_PLAN = [None,
            ("6 × 200 метров бег / 200 метров шагом", "Бег интервалами: 6 × 200 метров."),
            ("6 × 200 метров бег / 200 метров шагом", "Бег интервалами: 6 × 200 метров."),
            ("4 × 400 метров бег / 200 метров шагом", "Бег интервалами: 4 × 400 метров."),
            ("5 × 400 метров бег / 200 метров шагом", "Бег интервалами: 5 × 400 метров."),
            ("4 × 600 метров бег / 200 метров шагом", "Бег интервалами: 4 × 600 метров."),
            ("3 × 800 метров бег / 200 метров шагом", "Бег интервалами: 3 × 800 метров."),
            ("3 × 800 метров бег / 200 метров шагом", "Бег интервалами: 3 × 800 метров."),
            ("2 км непрерывно", "Бег 2 км непрерывно."),
            ("2 км непрерывно", "Бег 2 км непрерывно."),
            ("2.5 км непрерывно", "Бег 2.5 км непрерывно."),
            ("2.5 км непрерывно", "Бег 2.5 км непрерывно."),
            ("3 км непрерывно", "Бег 3 км непрерывно.")]
RUN_PACE = "разговорный темп: если дыхание рвётся — переходи на шаг, это не проигрыш"


def bike(minutes: int, note: str | None = None) -> dict:
    return it("bike_erg", f"{kg(BIKE_KM[minutes])} км", note)


def warmup(minutes: int = 6, note: str | None = None) -> list[dict]:
    return [bike(minutes, note), it("band_pull_apart", "2 × 15")]


def shoulder_block(face: float, block: int, row: float | None, sets: int = 3) -> dict:
    items = [
        it("face_pull", f"{sets} × 15 · {kg(face)} кг"),
        it("band_external_rotation", f"2 × 15 · резина {ER_BAND[block]}"),
    ]
    if row is not None:
        items.append(it("chest_supported_row", f"{sets} × 12 · {kg(row)} кг", "упор грудью — спина разгружена"))
    return blk("Защита плеча", items, "обязательный блок")


def cooldown(move: str) -> dict:
    return blk("Заминка", [it(move, "60 секунд × 2")])


# ---------- bench progressions (10 kg steps) ----------
# Block 1: re-adaptation after a 10-year break. На контрольном дне 28 он взял
# 100 кг на раз вместо теста на повторы с 70, поэтому дальше веса считаются от
# сотни: рабочий тяжёлый день 80 → 90, объёмный 70 → 90, одиночные 100 → 110.
# Страховка на случай, если сотня была на пределе, — правило RPE в примечании
# основного блока: подход тяжелее RPE 9 → остальные на повтор меньше.
BH = {
    1: [None,
        {"ramp": "20 кг × 10 · 30 кг × 5", "main": "4 × 8, 50 кг", "sub": "Адаптация. Жим 50 × 8."},
        {"ramp": "20 кг × 10 · 30 кг × 5", "main": "5 × 8, 50 кг", "sub": "Адаптация. Жим 50 × 8, пятый подход."},
        {"ramp": "20 кг × 10 · 40 кг × 5", "main": "5 × 5, 60 кг", "sub": "Первая силовая. Жим 60 × 5."}],
    2: [{"ramp": "20 кг × 10 · 40 кг × 5 · 60 кг × 3 · 70 кг × 1", "main": "5 × 3, 80 кг", "sub": "Сила. Первый блок от новой сотни. Вчера был тест — без добивки."},
        {"ramp": "20 кг × 10 · 40 кг × 5 · 60 кг × 3 · 70 кг × 1", "main": "6 × 3, 80 кг", "sub": "Сила. Жим 80 × 3, шесть подходов."},
        {"ramp": "20 кг × 10 · 40 кг × 5 · 60 кг × 3 · 70 кг × 1", "top": "1 × 1, 90 кг", "top_note": "одиночный только если разминка лёгкая (RPE ≤ 8)", "main": "5 × 4, 80 кг", "sub": "Сила. Жим 80 × 4 и заход на 90."},
        {"ramp": "20 кг × 10 · 40 кг × 5", "main": "3 × 3, 70 кг", "sub": "Разгрузка. Легко и быстро."}],
    3: [{"ramp": "20 кг × 10 · 40 кг × 5 · 60 кг × 3 · 80 кг × 1", "main": "5 × 2, 90 кг", "sub": "Сила. Девяносто в рабочих подходах. Вчера был тест — без добивки."},
        {"ramp": "20 кг × 10 · 40 кг × 5 · 60 кг × 3 · 80 кг × 1", "main": "6 × 2, 90 кг", "back": "2 × 5, 70 кг", "sub": "Сила. Жим 90 × 2, шесть подходов."},
        {"ramp": "20 кг × 10 · 40 кг × 5 · 60 кг × 3 · 80 кг × 1", "top": "1 × 1, 100 кг", "top_note": "сотня только со страхующим и только если разминка лёгкая (RPE ≤ 8)", "main": "4 × 3, 90 кг", "sub": "Сила. Сотня на раз и тройки на 90."},
        {"ramp": "20 кг × 10 · 40 кг × 5", "main": "3 × 3, 70 кг", "sub": "Разгрузка. Легко и быстро."}],
    4: [{"ramp": "20 кг × 10 · 40 кг × 5 · 60 кг × 3 · 80 кг × 1", "main": "4 × 3, 90 кг", "sub": "Пик. Вчера был тест — только тройки на 90."},
        {"ramp": "20 кг × 10 · 40 кг × 5 · 60 кг × 3 · 80 кг × 2 · 90 кг × 1", "top": "1 × 1, 110 кг", "top_note": "110 только если 100 на разминке идёт легко (RPE ≤ 8), иначе 100 × 1", "main": "3 × 3, 90 кг", "sub": "Пик. Заход на 110 без героизма."},
        {"ramp": "20 кг × 10 · 40 кг × 5", "main": "3 × 3, 70 кг", "top": "1 × 1, 90 кг", "top_note": "одиночный быстрый и лёгкий", "sub": "Подводка. Завтра контрольный день."}],
}
BV = {   # объёмный жим раз в неделю: 4 входа на блок
    1: [("20 кг × 10", "3 × 12, 40 кг"), ("20 кг × 10 · 30 кг × 5", "3 × 10, 50 кг"),
        ("20 кг × 10 · 30 кг × 5", "4 × 10, 50 кг"), ("20 кг × 10 · 40 кг × 5", "4 × 8, 50 кг")],
    2: [("20 кг × 10 · 50 кг × 5", "4 × 8, 70 кг"), ("20 кг × 10 · 50 кг × 5", "5 × 8, 70 кг"),
        ("20 кг × 10 · 50 кг × 5 · 70 кг × 2", "4 × 6, 80 кг"), ("20 кг × 10 · 40 кг × 5", "3 × 8, 60 кг")],
    3: [("20 кг × 10 · 50 кг × 5 · 70 кг × 2", "4 × 6, 80 кг"), ("20 кг × 10 · 50 кг × 5 · 70 кг × 2", "5 × 6, 80 кг"),
        ("20 кг × 10 · 50 кг × 5 · 70 кг × 2 · 80 кг × 1", "6 × 4, 90 кг"), ("20 кг × 10 · 50 кг × 5", "3 × 6, 70 кг")],
    4: [("20 кг × 10 · 50 кг × 5 · 70 кг × 2 · 80 кг × 1", "4 × 4, 90 кг"), ("20 кг × 10 · 50 кг × 5 · 70 кг × 2 · 80 кг × 1", "5 × 4, 90 кг"),
        ("20 кг × 10 · 50 кг × 5", "3 × 5, 80 кг"), ("20 кг × 10 · 40 кг × 5", "3 × 5, 70 кг")],
}
# Жим узким хватом — второе движение тяжёлого дня во всех силовых блоках: это
# лучший тяжёлый жим на трицепс из того, что он делает, и он же дожим в жиме.
# Три подхода, не больше: прямой работы на руки теперь три дня в неделю.
BH_SECOND = {
    1: [None, ("db_incline_press", "3 × 10 · 12.5 кг в руке"), ("db_incline_press", "3 × 10 · 15 кг в руке"),
        ("db_incline_press", "3 × 10 · 17.5 кг в руке")],
    2: [("close_grip_bench", "3 × 8, 50 кг"), ("close_grip_bench", "3 × 8, 60 кг"),
        ("close_grip_bench", "3 × 6, 60 кг"), ("close_grip_bench", "2 × 8, 40 кг")],
    3: [("close_grip_bench", "3 × 8, 60 кг"), ("close_grip_bench", "3 × 8, 60 кг"),
        ("close_grip_bench", "3 × 6, 70 кг"), ("close_grip_bench", "2 × 8, 50 кг")],
    4: [("close_grip_bench", "3 × 6, 70 кг"), ("close_grip_bench", "3 × 6, 70 кг"), None],
}
TEST_REP = {
    28: (70, "20 кг × 10 · 40 кг × 5 · 50 кг × 3 · 60 кг × 1",
         "расчёт: 3 → 77 · 4 → 79 · 5 → 82 · 6 → 84 · 7 → 86 · если 70 не идёт — сделай 60 на максимум, формула та же", 80),
    56: (90, "20 кг × 10 · 40 кг × 5 · 60 кг × 3 · 80 кг × 1",
         "расчёт: 2 → 96 · 3 → 99 · 4 → 102 · 5 → 105 · 6 → 108", 100),
    84: (100, "20 кг × 10 · 40 кг × 5 · 60 кг × 3 · 80 кг × 2 · 90 кг × 1",
         "расчёт: 2 → 107 · 3 → 110 · 4 → 113 · 5 → 117 · 6 → 120", 110),
}

# ---------- per-block tables for other days ----------
# Day 4 log: pulldown done at 80 kg x 10 x 4 where 35 was prescribed, dead hang
# 52 s. Back is far ahead of the original estimate, so pulling starts from the
# real number and steps 5 kg a week.
PULL = {
    1: [("lat_pulldown_neutral", ["4 × 10 · 80 кг", "4 × 10 · 85 кг", "4 × 12 · 85 кг", "4 × 10 · 80 кг"]),
        ("db_row", ["3 × 10 · 20 кг", "3 × 10 · 22.5 кг", "3 × 12 · 22.5 кг", "3 × 10 · 25 кг"])],
    2: [("assisted_pull_up", ["4 × 6 · противовес 25 кг", "4 × 6 · противовес 20 кг", "4 × 6 · противовес 15 кг", "3 × 6 · противовес 25 кг"]),
        ("seated_row", ["4 × 10 · 60 кг", "4 × 10 · 65 кг", "4 × 10 · 70 кг", "3 × 10 · 55 кг"])],
    3: [("assisted_pull_up", ["4 × 6 · противовес 15 кг", "4 × 6 · противовес 10 кг", "4 × 6 · противовес 5 кг", "3 × 6 · противовес 20 кг"]),
        ("db_row", ["3 × 8 · 27.5 кг", "3 × 8 · 30 кг", "3 × 8 · 32.5 кг", "3 × 8 · 25 кг"])],
    4: [("neutral_pull_up", ["4 × максимум − 1 · если не выходит, гравитрон 10 кг", "3 × 5 · гравитрон по самочувствию"]),
        ("seated_row", ["4 × 8 · 75 кг", "3 × 8 · 65 кг"])],
}
DELT = {1: 5, 2: 5, 3: 7.5, 4: 7.5}

# ---------- руки ----------
# Руки — заявленный приоритет: прямая работа трижды в неделю по четыре подхода
# плюс лёгкий заход в воскресенье. Французский жим он не делает (сказал прямо
# 29.10), поэтому движения из-за головы из программы убраны: трицепс берёт
# тяжёлый жим узким хватом на жимовом дне, разгибания на блоке двумя хватами и
# отжимания узким хватом. Бицепс — на наклонной (растянутое положение) и
# молотковым хватом на брахиалис: он лежит под бицепсом и добавляет руке
# толщину, а не только «шишку». Пара движений закреплена за днём, чтобы вес
# было с чем сравнивать неделя к неделе.
ARM_PAIR = {"pull": ("incline_curl", "rope_pushdown"),
            "bench_volume": ("cable_curl", "tricep_pushdown"),
            "legs_b": ("hammer_curl", "push_up_close")}
PER_HAND = {"incline_curl", "hammer_curl", "db_curl"}
BODYWEIGHT_ARM = {"push_up_close": ["4 × 12", "4 × 15", "4 × 12", "3 × 15"]}
ARM_NOTES = {
    "incline_curl": "вниз до полного выпрямления — бицепс отзывается на растянутое положение",
    "hammer_curl": "хват молотком — это брахиалис, он добавляет руке толщину",
    "cable_curl": "локти прижаты к корпусу, корпусом не помогаешь",
    "rope_pushdown": "локти у корпуса и на месте, внизу разводи канат в стороны",
    "tricep_pushdown": "обратный хват, локти прижаты — акцент на внутренний пучок",
    "push_up_close": "кисти под грудью, локти вдоль корпуса — это трицепс, а не грудь",
}
# Двойная прогрессия внутри блока: повторы вверх, потом вес, четвёртая неделя легче.
ARM_SETS = ["4 × 10", "4 × 12", "4 × 10", "3 × 12"]
ARM_START = {  # рабочий вес первой недели блока, +2.5 кг на третьей
    "incline_curl": {1: 7.5, 2: 10, 3: 12.5, 4: 15},
    "hammer_curl": {1: 10, 2: 12.5, 3: 15, 4: 17.5},
    "cable_curl": {1: 12.5, 2: 17.5, 3: 20, 4: 22.5},
    "rope_pushdown": {1: 15, 2: 20, 3: 22.5, 4: 25},
    "tricep_pushdown": {1: 15, 2: 20, 3: 22.5, 4: 25},
}
# Воскресный пампинг: лёгкий объём, брахиорадиалис и предплечья. Восстановлению
# не мешает, а предплечье и обратный хват — это видимая толщина руки.
ARM_PUMP = {"db_curl": {1: 7.5, 2: 10, 3: 10, 4: 12.5},
            "rope_pushdown": {1: 12.5, 2: 15, 3: 17.5, 4: 17.5},
            "wrist_curl": {1: 5, 2: 5, 3: 7.5, 4: 7.5}}


def arm_text(move: str, block: int, i: int) -> str:
    if move in BODYWEIGHT_ARM:
        return BODYWEIGHT_ARM[move][min(i, 3)]
    weight = ARM_START[move][block] + (2.5 if i == 2 else 0)
    return f"{ARM_SETS[min(i, 3)]} · {kg(weight)} кг" + (" в руке" if move in PER_HAND else "")


def arm_block(dtype: str, block: int, i: int) -> dict:
    """Бицепс и трицепс — антагонисты: суперсетом прямая работа на руки
    укладывается в шесть минут и не выносит день за обеденное окно."""
    pair = ARM_PAIR[dtype]
    step = "отжимания: добрал все повторы — в следующий раз подход длиннее" \
        if pair[1] in BODYWEIGHT_ARM else STEP_UP
    return blk("Суперсет · руки", [it(m, arm_text(m, block, i), ARM_NOTES[m]) for m in pair],
               "чередуй подходы, отдых 60 секунд · " + step)


def arm_pump_block(block: int) -> dict:
    return blk("Руки и предплечья", [
        it("db_curl", f"2 × 15 · {kg(ARM_PUMP['db_curl'][block])} кг в руке", "легко, на кровь — не в отказ"),
        it("rope_pushdown", f"2 × 15 · {kg(ARM_PUMP['rope_pushdown'][block])} кг"),
        it("reverse_curl", "2 × 15 · гриф 20 кг", "обратный хват: брахиорадиалис и предплечье, вес здесь не нужен"),
        it("wrist_curl", f"2 × 15 · {kg(ARM_PUMP['wrist_curl'][block])} кг в руке", "предплечье на бедре, двигаются только кисти"),
    ], "объём без усталости: лёгкий день — лучшее место для рук и предплечий")

LEGS_MAIN = {
    1: ("goblet_squat", ["3 × 10 · 17.5 кг", "3 × 10 · 20 кг", "3 × 12 · 20 кг", "4 × 10 · 20 кг"], "таз ниже колена, спина нейтральная"),
    2: ("leg_press", ["4 × 10 · 80 кг", "4 × 10 · 90 кг", "4 × 10 · 100 кг", "3 × 10 · 70 кг"], "поясница прижата, внизу таз не подкручивать"),
    3: ("hack_squat", ["4 × 8 · 40 кг", "4 × 8 · 50 кг", "4 × 8 · 60 кг", "3 × 8 · 40 кг"], "глубина до параллели, колени по линии стоп"),
    4: ("leg_press", ["4 × 8 · 110 кг", "3 × 8 · 100 кг"], "поясница прижата, внизу таз не подкручивать"),
}
LEGS_HINGE = {1: ("kb_deadlift", "3 × 12", [16, 20, 24, 24]), 2: ("kb_swing", "3 × 15", [16, 16, 20, 16]),
              3: ("kb_swing", "3 × 15", [20, 20, 24, 16]), 4: ("kb_deadlift", "3 × 10", [28, 24])}
LEGS_UNI = {1: ("split_squat", ["3 × 8 на ногу · 5", "3 × 8 на ногу · 7.5", "3 × 10 на ногу · 7.5", "3 × 8 на ногу · 10"]),
            2: ("split_squat", ["3 × 8 на ногу · 10", "3 × 8 на ногу · 12.5", "3 × 10 на ногу · 12.5", "3 × 8 на ногу · 7.5"]),
            3: ("step_up", ["3 × 8 на ногу · 12.5", "3 × 8 на ногу · 15", "3 × 10 на ногу · 15", "3 × 8 на ногу · 10"]),
            4: ("split_squat", ["3 × 8 на ногу · 15", "3 × 8 на ногу · 12.5"])}
LEG_EXT = {1: [20, 20, 25, 25], 2: [30, 30, 35, 25], 3: [35, 40, 40, 30], 4: [40, 35]}

LEGS_B = {  # (hip thrust kg, rdl sets+kg, reverse lunge kg, leg curl kg, calf kg) — раз в неделю
    # Веса от факта дня 20: хип трастер 70, румынская 60. Румынская упирается
    # в 80 — протрузия, дальше растут подходы, а не вес.
    1: [(40, "3 × 8, 30 кг", 7.5, 25, 40), (50, "3 × 8, 40 кг", 10, 30, 50),
        (50, "3 × 8, 40 кг", 10, 30, 50), (60, "3 × 8, 50 кг", 12.5, 35, 50)],
    2: [(70, "3 × 8, 60 кг", 12.5, 35, 60), (80, "3 × 8, 60 кг", 15, 40, 60),
        (80, "4 × 8, 70 кг", 15, 40, 70), (60, "3 × 8, 60 кг", 10, 30, 50)],
    3: [(90, "4 × 8, 70 кг", 17.5, 45, 70), (90, "4 × 8, 80 кг", 17.5, 45, 70),
        (100, "4 × 10, 80 кг", 20, 50, 80), (70, "3 × 8, 60 кг", 12.5, 35, 60)],
    4: [(100, "4 × 8, 80 кг", 20, 50, 80), (100, "4 × 10, 80 кг", 20, 50, 80),
        (80, "3 × 8, 70 кг", 15, 40, 60), (70, "2 × 8, 60 кг", 12.5, 35, 50)],
}
SHORT = {1: [(10, 17.5, 10, 20), (12, 20, 12, 25)], 2: [(12, 22.5, 12, 30), (10, 20, 10, 25)],
         3: [(15, 25, 12, 35), (12, 22.5, 10, 30)], 4: [(8, 20, 8, 20)]}
FINISHER = {
    1: ("Финишер · 3 круга на время", "цель — быстрее, чем в прошлый раз · записать время",
        [("air_bike", "60 секунд в темпе"), ("burpee_step", "8 повторов"), ("suitcase_carry", "30 метров · 17.5 кг")]),
    2: ("Финишер · AMRAP 8 минут", "сколько кругов успеешь · записать раунды",
        [("front_rack_carry", "30 метров · 16 кг в руке"), ("push_up", "10 повторов"), ("dead_bug", "8 на сторону")]),
    3: ("Финишер · 4 круга на время", "цель — быстрее, чем в прошлый раз · записать время",
        [("air_bike", "90 секунд в темпе"), ("burpee_step", "10 повторов"), ("suitcase_carry", "30 метров · 22.5 кг")]),
    4: ("Финишер · AMRAP 8 минут", "сколько кругов успеешь · записать раунды",
        [("front_rack_carry", "30 метров · 20 кг в руке"), ("push_up", "12 повторов"), ("bird_dog", "8 на сторону")]),
}
MINI_FINISHER = {  # 5 minutes after volume bench day
    1: "5 × 20 секунд быстро / 40 секунд легко",
    2: "6 × 20 секунд быстро / 40 секунд легко",
    3: "8 × 20 секунд быстро / 40 секунд легко",
    4: "6 × 20 секунд быстро / 40 секунд легко",
}
MOBILITY = [("hip_90_90", "cat_camel", "thoracic_rotation"), ("couch_stretch", "lat_stretch", "cat_camel"),
            ("hip_flexor_stretch", "pec_stretch_doorway", "thoracic_extension_roll"),
            ("thoracic_rotation", "hip_90_90", "lat_stretch")]
MOBILITY_NOTES = {"hip_90_90": "тянет в ягодице и бедре, не в колене — доверни таз, а не голень",
                  "couch_stretch": "колено на мягком, таз подкручен вперёд"}
REPS_MOBILITY = {"cat_camel", "thoracic_rotation", "thoracic_extension_roll"}
CORE = ["dead_bug", "pallof_press", "side_plank", "bird_dog"]
CORE_STEP = {1: 0, 2: 0, 3: 1, 4: 1}  # side plank +10 s, pallof +2.5 kg per step


def core_item(n: int, block: int, exclude: set[str] = frozenset()) -> dict:
    options = [m for m in CORE if m not in exclude]
    move, step = options[n % len(options)], CORE_STEP[block]
    text = {
        "dead_bug": "3 × 8 на сторону",
        "bird_dog": "3 × 8 на сторону",
        "side_plank": f"3 × {30 + 10 * step} секунд на сторону",
        "pallof_press": f"3 × 12 на сторону · {kg(10 + 2.5 * step)} кг",
    }[move]
    return it(move, text)


def grip_block(block: int, deload: bool, pull_day: bool) -> dict:
    farmer = {1: 20, 2: 22.5, 3: 25, 4: 27.5}[block] - (2.5 if deload else 0)
    wrist = 5 if block <= 2 else 7.5
    first = it("dead_hang", "3 × максимум секунд", "записать лучший") if pull_day \
        else it("farmer_hold_heavy", f"3 × 30 секунд · {kg(farmer)} кг в руке")
    return blk("Хват · 5 минут", [first, it("reverse_wrist_curl", f"3 × 15 · {kg(wrist)} кг в руке")],
               "последнее в тренировке · удержание на месте, не ходьба: спина нейтральная, плечи назад")


def leg_grip_block(block: int, deload: bool) -> dict:
    bell = {1: 16, 2: 20, 3: 24, 4: 24}[block] - (4 if deload else 0)
    pinch_s = {1: 20, 2: 25, 3: 30, 4: 35}[block] - (5 if deload else 0)
    return blk("Хват · 5 минут", [it("kb_farmer_hold", f"3 × 30 секунд · {bell} кг в руке"),
                                  it("plate_pinch", f"3 × {pinch_s} секунд · 2 блина по 5 кг в руке", "гладкой стороной наружу")],
               "последнее в тренировке · если тянет поясницу — вес на ступень ниже")


def finisher_block(block: int) -> dict:
    label, note, items = FINISHER[block]
    return blk(label, [it(m, t) for m, t in items], note)


# ---------- day builders ----------

def bench_heavy(d: int, block: int, i: int) -> dict:
    p = BH[block][i]
    deload = "Разгрузка" in p["sub"]
    sets = " + ".join(x for x in (p.get("top"), p["main"], p.get("back")) if x)
    note = " · ".join(x for x in (f"разминка: {p['ramp']}", p.get("top_note"),
                                  "добивка после основных" if p.get("back") else None,
                                  "пауза на груди, лопатки сведены") if x)
    items = [it("bb_bench_press", sets, note)]
    second = pick(BH_SECOND[block], i)
    if second:
        items.append(it(*second))
    # day 5 log: face pull done at 30 kg where 12.5 was prescribed
    face = 20 if deload else {1: 25, 2: 27.5, 3: 30, 4: 30}[block]
    row = 35 if deload else {1: 40, 2: 45, 3: 50, 4: 50}[block]
    blocks = [
        blk("Разминка", warmup(6, "пульс до 110")),
        blk("Основной блок", items[:1], "отдых 2–3 минуты · если подход тяжелее RPE 9 — остальные на повтор меньше"),
    ]
    if len(items) > 1:
        # Прямая работа на трицепс уехала в три отдельных дня, поэтому здесь
        # второе движение — тяжёлый жим, а не добивка разгибаниями.
        # antagonist supersets keep the day inside the 45-minute lunch window
        blocks += [
            blk("Суперсет · жим + тяга", [items[1], it("chest_supported_row", f"3 × 12 · {kg(row)} кг", "упор грудью — спина разгружена")],
                "чередуй подходы, отдых 60 секунд"),
            blk("Суперсет · защита плеча", [
                it("face_pull", f"3 × 15 · {kg(face)} кг", "без рывка корпусом; тянешь рывком — сбрось вес"),
                it("band_external_rotation", f"2 × 15 · резина {ER_BAND[block]}")],
                "круг без пауз, отдых 45 секунд между кругами · блок обязательный"),
        ]
    else:
        blocks.append(shoulder_block(face, block, row))
    if d < 99:
        blocks.append(grip_block(block, deload, pull_day=False))
    blocks.append(cooldown("pec_stretch_doorway"))
    return {"subtitle": p["sub"], "minutes": 45, "rules": rules(d, True), "blocks": blocks}


def bench_volume(d: int, block: int, i: int, n: int) -> dict:
    ramp, main = BV[block][i]
    # day 5 log: landmine done with a 10 kg plate where 5 was prescribed
    landmine = pick([10, 15, 15, 20, 20, 25, 25, 25, 30, 30, 30, 30], n)
    row = pick([40, 45, 45, 50, 50, 55, 55, 60, 60, 65, 65, 70], n)
    face = {1: 25, 2: 27.5, 3: 30, 4: 30}[block]
    sets, weight = main.split(", ")
    blocks = [
        blk("Разминка", warmup(5)),
        blk("Основной блок", [it("bb_bench_press", main, f"разминка: {ramp} · темп: 2 секунды вниз, мощно вверх"),
                              it("landmine_shoulder_press", f"3 × 10 на руку · блин {landmine} кг",
                                 "жим под углом — плечу безопаснее, чем над головой")],
            "отдых 90 секунд"),
        blk("Спина", [it("chest_supported_row", f"4 × 12 · {kg(row)} кг", "упор грудью — спина разгружена")]),
        arm_block("bench_volume", block, i),
        shoulder_block(face, block, None),
        blk("Финишер · 5 минут", [it("air_bike", MINI_FINISHER[block])], "интервалы"),
    ]
    return {"subtitle": f"Объём. Жим {weight}, {sets}.", "minutes": 45, "rules": rules(d, True), "blocks": blocks}


def pull(d: int, block: int, i: int, w: int, deload: bool, taper: bool) -> dict:
    (v_move, v_list), (h_move, h_list) = PULL[block]
    delt = "db_rear_delt_fly" if w % 2 == 0 else "db_lateral_raise"
    delt_kg = DELT[block] - (2.5 if deload else 0)
    blocks = [
        blk("Разминка", warmup(6) + [it("face_pull", "2 × 15", "лёгкий вес")]),
        blk("Основной блок", [it(v_move, pick(v_list, i), STEP_UP), it(h_move, pick(h_list, i))], "отдых 90 секунд"),
        blk("Плечи", [it(delt, f"3 × 15 · {kg(delt_kg)} кг в руке", "до уровня плеч, не выше")]),
        arm_block("pull", block, i),
    ]
    if w % 2 == 0:
        blocks.append(grip_block(block, deload, pull_day=True))
    elif not taper and not deload:
        blocks.append(finisher_block(block))
    blocks.append(cooldown("lat_stretch"))
    return {"subtitle": "Спина, задняя дельта, руки.", "minutes": 45, "rules": rules(d, True), "blocks": blocks}


# Присед со штангой: двойная прогрессия (5 × 5 → 5 × 6 → +10 кг). Осевая нагрузка с дня 22,
# до этого — жим ногами. Веса от факта: гоблет 20, жим ногами 100, гакк 60.
SQUAT = {
    1: ["5 × 5, 40 кг"],   # первый заход: техника, не вес
    2: ["5 × 5, 50 кг", "5 × 6, 50 кг", "5 × 5, 60 кг", "3 × 5, 40 кг"],
    3: ["5 × 6, 60 кг", "5 × 5, 70 кг", "5 × 6, 70 кг", "3 × 5, 50 кг"],
    4: ["5 × 5, 80 кг", "5 × 6, 80 кг", "5 × 3, 90 кг", "3 × 5, 60 кг"],
}


def legs_a(d: int, block: int, i: int, w: int, deload: bool, taper: bool, n: int) -> dict:
    if d >= 23 and block in SQUAT:
        return legs_squat(d, block, i, deload, taper, n)
    m_move, m_list, m_note = LEGS_MAIN[block]
    h_move, h_sets, h_list = LEGS_HINGE[block]
    u_move, u_list = LEGS_UNI[block]
    finisher = finisher_block(block) if w % 2 == 1 and not taper and not deload else None
    in_finisher = {x["movement"] for x in finisher["items"]} if finisher else set()
    blocks = [
        blk("Разминка", [bike(6), it("glute_bridge", "2 × 12", "включить ягодицы перед приседом")]),
        blk("Основной блок", [it(m_move, pick(m_list, i), f"разминка: 1 × 10 с половиной рабочего веса · {m_note} · {STEP_UP}"),
                              it(h_move, f"{h_sets} · {pick(h_list, i)} кг", "спина нейтральная, движение из таза"),
                              it(u_move, f"{pick(u_list, i)} кг в руке")]),
        blk("Изоляция и корпус", [it("leg_extension", f"3 × 15 · {pick(LEG_EXT[block], i)} кг", "полная амплитуда, вверху пауза 1 секунда"),
                                  core_item(n, block, in_finisher)], "суперсетом, отдых 45 секунд"),
    ]
    if w % 2 == 0:
        blocks.append(leg_grip_block(block, deload))
    elif finisher:
        blocks.append(finisher)
    blocks.append(cooldown("hip_flexor_stretch"))
    return {"subtitle": "Квадрицепс, таз, корпус.", "minutes": 45, "rules": rules(d, True), "blocks": blocks}


def legs_squat(d: int, block: int, i: int, deload: bool, taper: bool, n: int) -> dict:
    """Приседание первым, потом задняя цепь и одностороннее — подсобка по
    категориям 5/3/1 (ноги/кор), а не россыпь мелочи."""
    h_move, h_sets, h_list = LEGS_HINGE[block]
    u_move, u_list = LEGS_UNI[block]
    main = pick(SQUAT[block], i)
    blocks = [
        blk("Разминка", [bike(6), it("glute_bridge", "2 × 12", "включить ягодицы перед приседом")]),
        blk("Основной блок", [it("back_squat", main,
                                 "разминка: гриф × 10 · половина рабочего × 5 · спина нейтральная, колени по линии стоп")],
            "отдых 2–3 минуты · если подход тяжелее RPE 8 — следующий на повтор меньше"),
        blk("Подсобка · ноги и кор", [it(h_move, f"{h_sets} · {pick(h_list, i)} кг", "движение из таза, спина нейтральная"),
                                      it(u_move, f"{pick(u_list, i)} кг в руке"),
                                      core_item(n, block)], "25–50 повторов на категорию, отдых 60 секунд"),
    ]
    if not taper and not deload:
        blocks.append(leg_grip_block(block, deload))
    blocks.append(cooldown("hip_flexor_stretch"))
    return {"subtitle": f"Присед {main}.", "minutes": 45, "rules": rules(d, True), "blocks": blocks}


def legs_b(d: int, block: int, i: int, deload: bool) -> dict:
    hip, rdl, lunge, curl, calf = LEGS_B[block][i]
    blocks = [
        blk("Разминка", [bike(6), it("bird_dog", "2 × 8 на сторону")]),
        blk("Основной блок", [it("hip_thrust_machine", f"3 × 10 · {hip} кг", "пауза 1 секунда вверху"),
                              it("rdl_bb", rdl, "штанга по бёдрам, спина нейтральная, до середины голени"),
                              it("reverse_lunge", f"3 × 8 на ногу · {kg(lunge)} кг в руке", "шаг назад — колену легче")]),
        blk("Изоляция", [it("leg_curl", f"3 × 12 · {curl} кг"), it("calf_raise_standing", f"3 × 15 · {calf} кг")]),
        arm_block("legs_b", block, i),
        leg_grip_block(block, deload),
        cooldown("hip_flexor_stretch"),
    ]
    return {"subtitle": "Задняя цепь, ягодичные, руки.", "minutes": 45, "rules": rules(d, True), "blocks": blocks}


def short_day(d: int, block: int, i: int) -> dict:
    push, carry, knees, hang = SHORT[block][i]
    before_test = (d + 1) in TEST_REP or d + 1 == 100
    first = it("glute_bridge", "15 повторов", "завтра тест жима — грудь не трогаем") if before_test \
        else it("push_up", f"{push} повторов")
    items = [first, it("suitcase_carry", f"30 метров · {kg(carry)} кг"),
             it("hanging_knee_raise", f"{knees} повторов", "без раскачки"),
             it("towel_hang" if d >= 22 else "dead_hang", f"{hang} секунд")]  # towel_hang unlocks on day 22
    return {"subtitle": "Короткий формат. EMOM 16 минут.", "minutes": 20, "rules": rules(d, False),
            "blocks": [blk("Разминка", [bike(3)]),
                       blk("EMOM 16 минут", items, "каждую минуту своё, четыре круга")]}


POOL_KICK = [4, 6, 6, 8, 8, 8, 8]       # 25 m lengths with the board, legs only
POOL_SWIM = [6, 6, 8, 8, 10, 10, 12]    # 25 m lengths of front crawl, easy pace


def pool_day(d: int, n: int) -> dict:
    """Pool day rebuilt from the day 6 log: the pool is 25 m, 50 m in one go is
    not there yet, and it is the lats that fill up, not the shoulders. So the
    volume sits on the board (legs), crawl comes in 25 m pieces with real rest,
    and breathing is trained on purpose instead of being endured."""
    kick, swim = POOL_KICK[n], POOL_SWIM[n]
    total = 100 + kick * 25 + swim * 25 + 100
    blocks = [
        blk("Разминка", [it("swim_breathing", "3 × 20 выдохов", "полный выдох в воду, вдох поворотом головы"),
                         it("swim_easy", "100 метров легко", "по 25 метров, отдых у бортика сколько нужно")]),
        blk("Ноги с доской", [it("swim_kick_board", f"{kick} × 25 метров", "руки вытянуты, спина отдыхает — это основной объём дня")],
            "отдых 30 секунд между отрезками"),
        blk("Кроль отрезками", [it("swim_intervals", f"{swim} × 25 метров", "спокойно, не на скорость: задача — доплыть ровно и продышать")],
            "отдых 45–60 секунд между отрезками · забились широчайшие — отдыхай дольше"),
    ]
    if n >= 1:
        blocks.append(blk("Контроль · 1 попытка", [it("swim_free", "50 метров непрерывно", "получилось — запиши в заметку; не получилось — просто вылезай, это цель, а не задание")],
                          "только после отдыха 2 минуты"))
    blocks.append(blk("Заминка", [it("swim_breast", "100 метров", "брассом или на спине, медленно — выдышаться")]))
    return {"subtitle": f"Вода. Ноги, дыхание, отрезки по 25. {total} метров.", "minutes": 35,
            "rules": rules(d, False), "blocks": blocks}


def light_day(d: int, block: int, n: int, walk: bool) -> dict:
    mob = MOBILITY[n % len(MOBILITY)]
    mob_items = [it(m, "2 × 10" if m in REPS_MOBILITY else "2 подхода", MOBILITY_NOTES.get(m)) for m in mob]
    run = pick(RUN_PLAN, n) if n < len(RUN_PLAN) else RUN_PLAN[-1]
    cardio_note = None
    if walk and run:
        text, sub = run
        minutes = 32
        cardio = [it("walk", "1 км", "разминка перед бегом · " + WALK_PACE), it("run", text, RUN_PACE)]
        cardio_note = "после бега 0.5 км шагом — остыть и восстановить дыхание"
    elif walk:
        km = WALK_KM[block]
        minutes = int(km * 10)
        cardio, sub = [it("walk", f"{kg(km)} км", WALK_PACE)], f"Ходьба {kg(km)} км и подвижность."
    else:
        km = RECOVERY_KM[block]
        minutes = int(km * 3)
        cardio = [it("bike_erg", f"{kg(km)} км", "пульс 110–125, лёгкий темп")]
        sub = f"Восстановление. Вело {kg(km)} км."
    if walk:   # беговой день: кардио и всё, подвижность уехала на воскресенье
        return {"subtitle": sub, "minutes": minutes + 5, "rules": rules(d, False),
                "blocks": [blk("Кардио", cardio, cardio_note)]}
    plank_s = {1: 20, 2: 25, 3: 30, 4: 30}[block]
    core = blk("Корпус · 5 минут", [it("bird_dog", "2 × 6 на сторону", "задержка 8–10 секунд в каждом повторе"),
                                    it("side_plank", f"2 × {plank_s} секунд на сторону")],
               "стабилизация спины, каждый лёгкий день")
    return {"subtitle": sub + " Руки и предплечья.", "minutes": minutes + 20, "rules": rules(d, False),
            "blocks": [blk("Кардио", cardio, cardio_note), arm_pump_block(block),
                       blk("Подвижность", mob_items, "по 60 секунд, где не указаны повторы"), core]}


def control_blocks() -> list[dict]:
    return [
        blk("Контроль формы", [it("push_up", "максимум чистых повторов", "грудь касается кулака, корпус прямой"),
                               it("dead_hang", "1 × максимум секунд")],
            "результаты — в заметку, сравни с прошлым контрольным днём"),
        shoulder_block(25, 1, None, sets=2),
        blk("Заминка", [it("walk", "1 км", "замеры: вес утром натощак, талия по пупку — в заметку"),
                        it("pec_stretch_doorway", "60 секунд × 2")]),
    ]


def rep_test(d: int) -> dict:
    weight, ramp, table, threshold = TEST_REP[d]
    test = blk("Тест жима", [it("bb_bench_press", f"{weight} кг × максимум повторов", f"разминка: {ramp} · {table}")],
               "стоп, когда чувствуешь: остался 1 повтор. Отказ не нужен. Галочка = подход сделан")
    return {"subtitle": f"Контрольный день. Жим {weight} кг на повторы, отжимания, вис, замеры.",
            "minutes": 50,
            "rules": f"Расчётный максимум = вес × (1 + повторы / 30). Ниже {threshold} кг — следующий блок жима на 10 кг легче. " + rules(d, False),
            "blocks": [blk("Разминка", warmup(6)), test] + control_blocks()}


def final_test(d: int) -> dict:
    test = blk("Тест жима", [it("bb_bench_press", "попытки: 100 кг → 110 кг → 120 кг, по одному повтору",
                                "разминка: 20 кг × 10 · 40 кг × 5 · 60 кг × 3 · 80 кг × 2 · 90 кг × 1 · "
                                "если 110 шло на пределе — 120 не ставь, это травма, а не результат")],
               "отдых 4–5 минут · страхующий обязателен · галочка = попытки сделаны, не обязательно взяты")
    return {"subtitle": "Финал. Жим на максимум, отжимания, вис, замеры. Сравни с днём 1.",
            "minutes": 55, "rules": "Сегодня подводишь итог 100 дней, а не одного подхода. " + rules(d, False),
            "blocks": [blk("Разминка", warmup(6)), test] + control_blocks()}


# ---------- orchestration ----------

def snap_kept_days(days: dict) -> None:
    """Closed days keep item count and order, because logs store checked indices.
    Only weights and movement codes are snapped to kit that actually exists."""
    fixes = {("1", "db_neutral_press"): "3 × 10 · 10 кг в руке", ("1", "db_row"): "3 × 12 · 15 кг",
             ("1", "suitcase_carry"): "30 метров · 17.5 кг"}
    # kit swaps in place: same slot, same position in the day, available equipment
    swaps = {"sit_up": ("dead_bug", "8 на сторону"),
             "elliptical": ("air_bike", None),
             "cable_external_rotation": ("band_external_rotation", "2 × 15 · резина лёгкая")}
    # closed days keep their work but switch to the distance format
    minutes_to_km = {"3 минуты": "1 км", "5 минут": "1.5 км", "6 минут": "2 км",
                     "15 минут": "5 км", "20 минут": "7 км", "30 минут": "3 км", "10 минут": "1 км"}
    for d in KEEP_DAYS:
        for b in days[str(d)]["payload"]["blocks"]:
            for item in b["items"]:
                key = (str(d), item["movement"])
                if key in fixes:
                    item["text"] = fixes[key]
                if item["movement"] in swaps:
                    code, text = swaps[item["movement"]]
                    item["movement"] = code
                    if text:
                        item["text"] = text
                if item["movement"] in ("walk", "bike_erg") and item["text"] in minutes_to_km:
                    item["text"] = minutes_to_km[item["text"]]
                # warm-up bench ramp would repeat the main lift: same slot, different movement
                if b["label"] == "Разминка" and item["movement"] == "bb_bench_press":
                    item.update(movement="push_up", text="2 × 10", note="разогреть грудь и плечи, без усилия")


def build_payload(d: int, dtype: str, block: int, i: int, n: int) -> dict:
    w = ((d - 1) % 28) // 7
    deload = block in (2, 3) and w == DELOAD_WEEK
    taper = d >= TAPER_FROM
    match dtype:
        case "bench_heavy":
            return bench_heavy(d, block, i)
        case "bench_volume":
            return bench_volume(d, block, i, n)
        case "pull":
            return pull(d, block, i, w, deload, taper)
        case "legs":
            return legs_a(d, block, i, w, deload, taper, n)
        case "legs_b":
            return legs_b(d, block, i, deload)

        case "light":
            return light_day(d, block, n, walk=True)
        case "light2":
            return light_day(d, block, n + 2, walk=False)
        case "test":
            return final_test(d) if d == 100 else rep_test(d)
    raise ValueError(f"day {d}: unknown day_type {dtype}")


def reschedule(data: dict) -> None:
    """Shift scheduled_on by the pauses already recorded, so dates match reality."""
    start = date.fromisoformat(data["state"]["started_on"])
    pauses = [(date.fromisoformat(p["from"]), date.fromisoformat(p["to"])) for p in data["state"].get("pauses", [])]
    for d in range(1, 101):
        planned = start + timedelta(days=d - 1)
        shift = sum((to - frm).days + 1 for frm, to in pauses if planned >= frm)
        data["days"][str(d)]["scheduled_on"] = (planned + timedelta(days=shift)).isoformat()


WEEK = ["bench_heavy", "legs", "light", "pull", "bench_volume", "legs_b", "light2"]
TEST_DAYS = {28, 56, 84, 100}
# Заголовок дня обязан следовать типу: иначе день с жимом остаётся подписан
# «Бассейн» от прошлого каркаса, и в приложении видно одно, а делаешь другое.
TITLES = {"bench_heavy": "Верх · толчок", "bench_volume": "Жим · объём", "pull": "Верх · тяга",
          "legs": "Ноги · квадрицепс", "legs_b": "Ноги · задняя цепь",
          "light": "Кардио · бег", "light2": "Восстановление", "test": "Контрольный день"}


def retitle_frozen(days: dict, frozen: set[int]) -> None:
    """Заголовок прошедшего дня тоже приводим к его типу. Состав дня при этом не
    меняется — меняется только подпись, и в «Истории» перестаёт стоять
    «Бассейн» над тренировкой задней цепи."""
    for d in sorted(frozen):
        dtype = days[str(d)]["day_type"]
        if d < 16 or dtype not in TITLES:
            continue   # дни 1–15 подписаны по факту того, что тогда делалось
        suffix = " · разгрузка" if "разгрузка" in days[str(d)]["title"] else ""
        days[str(d)]["title"] = title_for(d, dtype) + suffix


def title_for(d: int, dtype: str) -> str:
    if d == 100:
        return "Финал · максимум"
    if dtype == "legs" and d >= 23:
        return "Ноги · присед"
    return TITLES[dtype]


def retype_days(days: dict, keep: set[int]) -> None:
    """Weekly frame from day 16 on: bench twice, legs twice, one run day, one
    recovery day. Pool and the short EMOM day are gone — the pool preceded the
    illness and the EMOM day was too light to earn its slot."""
    for d in range(16, 101):
        if d in keep:
            continue
        days[str(d)]["day_type"] = "test" if d in TEST_DAYS else WEEK[(d - 15) % 7]


# Блоки, которые не держат день: их видно, их можно отметить, но заминка и
# пятиминутка хвата не должны обнулять всю сделанную работу.
BONUS_LABELS = ("Заминка", "Хват", "Финишер")


def mark_bonus(days: dict) -> None:
    """Пометка бонуса не меняет ни состав, ни порядок пунктов, поэтому её можно
    ставить и на прошедшие дни, где logs ссылаются на индексы."""
    for day in days.values():
        for part in ("payload", "variant"):
            for b in day[part].get("blocks", []):
                if any(w in b["label"] for w in BONUS_LABELS):
                    b["optional"] = True
                else:
                    b.pop("optional", None)


def frozen_days(data: dict) -> set[int]:
    """История неприкосновенна. logs хранят индексы отмеченных пунктов: если
    перестроить прошедший день, галочки начнут указывать на другие упражнения.
    Сегодняшний день тоже заморожен: в нём уже могут стоять галочки, поэтому
    правки программы вступают в силу с завтрашнего дня."""
    start = date.fromisoformat(data["state"]["started_on"])
    paused = sum((date.fromisoformat(p["to"]) - date.fromisoformat(p["from"])).days + 1
                 for p in data["state"].get("pauses", []))
    current = min(100, max(1, (date.today() - start).days - paused + 1))
    return set(range(1, current + 1))


def build(data: dict) -> dict:
    days = data["days"]
    done = frozen_days(data) | {int(k) for k, v in data.get("logs", {}).items()
                                if v.get("outcome") in ("done", "swap", "dayoff")}
    retype_days(days, done)
    retitle_frozen(days, done)
    per_block: dict[tuple[int, str], int] = {}
    per_type: dict[str, int] = {}
    for d in range(1, 101):
        day = days[str(d)]
        dtype, block = day["day_type"], day["block"]
        i = per_block.get((block, dtype), 0)
        n = per_type.get(dtype, 0)
        per_block[(block, dtype)], per_type[dtype] = i + 1, n + 1
        if d in KEEP_DAYS or d in done:
            continue
        w = ((d - 1) % 28) // 7
        deload = block in (2, 3) and w == DELOAD_WEEK
        title = title_for(d, dtype)
        if deload and dtype in ("bench_heavy", "bench_volume", "legs", "pull", "legs_b"):
            title += " · разгрузка"
        day["title"] = title
        day["payload"] = apply_re_entry(d, build_payload(d, dtype, block, i, n))
    snap_kept_days(days)
    mark_bonus(days)
    return data


def add_moves(moves: dict) -> None:
    for code, m in NEW_MOVES.items():
        url = "https://www.youtube.com/results?search_query=" + quote(f"{m['name_ru']} техника выполнения")
        moves[code] = {**m, "unlock_day": 1, "media_url": url}
    # breaststroke is a cool-down, not a skill to unlock: it is easier than crawl
    moves["swim_breast"]["unlock_day"] = 1
    # the knee is healthy, so running starts on the second light day instead of day 50
    moves["run"].update(unlock_day=10, unit="км",
                        cue="Короткий шаг, стопа под тазом, плечи расслаблены. "
                            "Темп разговорный: рвётся дыхание — переходи на шаг. "
                            "Дистанция растёт от интервалов к непрерывному бегу.")
    # cardio is measured in kilometres now, so the library says so too
    for code in ("walk", "bike_erg"):
        moves[code]["unit"] = "км"


def add_media(moves: dict) -> None:
    """Attach photos (media/ex/<id>/N.jpg) and Russian step-by-step technique to moves."""
    images = {k: v for k, v in json.loads(IMAGES_MAP.read_text(encoding="utf-8")).items() if not k.startswith("_")}
    steps = json.loads(STEPS_RU.read_text(encoding="utf-8"))
    for code, move in moves.items():
        move.pop("images", None)
        move.pop("steps", None)
        if code in images:
            files = [f"media/ex/{images[code]}/{n}.jpg" for n in (0, 1)]
            move["images"] = [f for f in files if (ROOT / f).is_file()]
        if code in steps:
            move["steps"] = steps[code]


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    add_moves(data["moves"])
    build(data)
    add_media(data["moves"])
    reschedule(data)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
