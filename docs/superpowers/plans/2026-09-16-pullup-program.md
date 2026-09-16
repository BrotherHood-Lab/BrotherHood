# Программа «Подтягивания 5×30» Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 30-week pull-up progression program to the SenPai bot and the training cabinet: the bot shows today's 5 set targets from the current week and a Сделал/Не сделал confirmation; the cabinet shows the same current-week targets. Rank logic is untouched.

**Architecture:** A fixed 30×5 table (`PULLUP_PLAN`) is duplicated as a Python constant in `bot.py` and a JS constant in `training.html`, per the existing project convention of mirroring `EXERCISE_CONFIG` between the two. Program position (`current_week`) lives in a new Supabase table `pullup_program`, separate from `exercise_logs` (which keeps recording one PR number per day exactly as before). The bot's `/go` conversation gets two new states for the pull-up-specific flow; the cabinet's existing card renderer gets one extra block.

**Tech Stack:** Python 3 (`python-telegram-bot` 21.6, `requests`), vanilla JS in a static HTML file, Supabase (PostgREST).

## Global Constraints

- Do not rename or restructure `EXERCISE_CONFIG`, `RANK_ORDER`, or any rank-calculation function (`rank_for_value`/`rankForValue`, `next_rank_after`) — see [spec §Совместимость с разрядами](../specs/2026-09-16-pullup-program-design.md).
- `exercise_logs` keeps its current meaning for `pullups`: one PR number per day, unit `"раз"`.
- `PULLUP_PLAN` values must match the spec's table exactly (verified by unit test against the "Всего" row).
- `Nutrition/training.html` and `Training-deploy/training/index.html` must stay byte-identical after this work (they are currently identical — see spec).
- No new runtime dependency: use Python's stdlib `unittest`, not pytest (none is installed for this bot).

---

## Task 1: Create the `pullup_program` table in Supabase (manual)

This is a manual step in the Supabase dashboard — there is no migrations setup in this repo (checked: no `.sql` files, no migration tooling), and table creation isn't available through the REST key the bot uses.

- [ ] **Step 1: Run this SQL in the Supabase SQL Editor** (project `xcodcnqioajyqiiyfbrk`, per [project-architecture memory](../../../CLAUDE.md))

```sql
create table public.pullup_program (
  user_id text primary key,
  current_week integer not null default 1 check (current_week between 1 and 30),
  started_at date not null default current_date
);
```

- [ ] **Step 2: Check Row Level Security**

Open Table Editor → `exercise_logs` → check whether RLS is enabled and, if so, what policy lets the bot's key read/write it. Apply the same policy (or "RLS disabled", whichever `exercise_logs` uses) to `pullup_program`, so the bot's existing `SUPABASE_KEY` can read and write it the same way it already does for `exercise_logs`.

- [ ] **Step 3: Verify with a manual REST call**

Run this from a shell with the real `SUPABASE_URL`/`SUPABASE_KEY` (from `Brotherhood - bot/SenPai/.env`, not committed):

```bash
curl -s "$SUPABASE_URL/rest/v1/pullup_program" -H "apikey: $SUPABASE_KEY" -H "Authorization: Bearer $SUPABASE_KEY"
```

Expected: `[]` (empty array, HTTP 200) — table exists and is reachable, not a 404/permission error.

---

## Task 2: Plan table and pure helper functions (with unit tests)

**Files:**
- Modify: `Brotherhood - bot/SenPai/bot.py` (insert after line 99, before line 101)
- Create: `Brotherhood - bot/SenPai/test_pullup_plan.py`

**Interfaces:**
- Produces: `PULLUP_PLAN: list[tuple[int, int, int, int, int]]` (30 entries, index 0 = week 1), `find_starting_week(first_set: int) -> int` (1–30), `plan_for_week(week: int) -> tuple[int, int, int, int, int]` (clamps 1–30).

- [ ] **Step 1: Write the failing tests**

Create `Brotherhood - bot/SenPai/test_pullup_plan.py`:

```python
import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_KEY", "test-key")

import unittest

from bot import PULLUP_PLAN, find_starting_week, plan_for_week


class PullupPlanTests(unittest.TestCase):
    def test_plan_has_30_weeks_of_5_sets(self):
        self.assertEqual(len(PULLUP_PLAN), 30)
        for week_targets in PULLUP_PLAN:
            self.assertEqual(len(week_targets), 5)

    def test_week_1_targets(self):
        self.assertEqual(PULLUP_PLAN[0], (6, 5, 5, 4, 3))

    def test_week_30_targets(self):
        self.assertEqual(PULLUP_PLAN[29], (26, 15, 14, 14, 13))

    def test_weekly_totals_match_source_table(self):
        totals = [sum(week) for week in PULLUP_PLAN]
        self.assertEqual(totals, [
            23, 26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52,
            54, 56, 58, 60, 62, 64, 66, 68, 70, 72, 74, 76, 78, 80, 82,
        ])

    def test_plan_for_week_clamps_below_1(self):
        self.assertEqual(plan_for_week(0), PULLUP_PLAN[0])

    def test_plan_for_week_clamps_above_30(self):
        self.assertEqual(plan_for_week(99), PULLUP_PLAN[29])

    def test_find_starting_week_exact_run_of_matches(self):
        # неделя 6 и 7 обе имеют Подход1=10, неделя 8 уже требует 11 —
        # должна выбираться более поздняя из подходящих (7)
        self.assertEqual(find_starting_week(10), 7)

    def test_find_starting_week_below_minimum(self):
        self.assertEqual(find_starting_week(3), 1)

    def test_find_starting_week_above_maximum(self):
        self.assertEqual(find_starting_week(50), 30)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `Brotherhood - bot/SenPai/`:

```bash
python -m unittest test_pullup_plan.py -v
```

Expected: `ImportError: cannot import name 'PULLUP_PLAN' from 'bot'` (or similar — the names don't exist yet).

- [ ] **Step 3: Add `PULLUP_PLAN` and the pure helpers to `bot.py`**

In `Brotherhood - bot/SenPai/bot.py`, insert this block immediately after line 99 (`EXERCISE_ORDER = [...]`) and before line 101 (`ASK_NAME, CHOOSING, ENTERING = range(3)`):

```python
# Таблица прогрессии подтягиваний 5x30 — 30 недель, 5 подходов, индекс 0 = неделя 1.
# Зеркалируется в JS-константе PULLUP_PLAN в training.html — держать в соответствии.
PULLUP_PLAN = [
    (6, 5, 5, 4, 3), (7, 6, 5, 4, 4), (8, 6, 5, 5, 4), (8, 7, 5, 5, 5), (9, 7, 6, 5, 5),
    (10, 7, 6, 6, 5), (10, 8, 6, 6, 6), (11, 8, 7, 6, 6), (12, 8, 7, 7, 6), (12, 9, 7, 7, 7),
    (13, 9, 8, 7, 7), (14, 9, 8, 8, 7), (14, 10, 8, 8, 8), (15, 10, 9, 8, 8), (16, 10, 9, 9, 8),
    (16, 11, 9, 9, 9), (17, 11, 10, 9, 9), (18, 11, 10, 10, 9), (18, 12, 10, 10, 10), (19, 12, 11, 10, 10),
    (20, 12, 11, 11, 10), (20, 13, 11, 11, 11), (21, 13, 12, 11, 11), (22, 13, 12, 12, 11), (22, 14, 12, 12, 12),
    (23, 14, 13, 12, 12), (24, 14, 13, 13, 12), (24, 15, 13, 13, 13), (25, 15, 14, 13, 13), (26, 15, 14, 14, 13),
]


def plan_for_week(week: int) -> tuple:
    """Целевые 5 подходов для недели, week зажимается в диапазон 1..30."""
    week = max(1, min(30, week))
    return PULLUP_PLAN[week - 1]


def find_starting_week(first_set: int) -> int:
    """Максимальная неделя плана, где Подход1 <= first_set (колонка Подход1
    не убывает от недели к неделе, так что это просто её последнее вхождение
    не выше first_set); неделя 1, если first_set меньше минимума таблицы."""
    week = 1
    for i, targets in enumerate(PULLUP_PLAN, start=1):
        if targets[0] <= first_set:
            week = i
        else:
            break
    return week

```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m unittest test_pullup_plan.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add "Brotherhood - bot/SenPai/bot.py" "Brotherhood - bot/SenPai/test_pullup_plan.py"
git commit -m "Add pull-up 5x30 plan table and pure lookup helpers"
```

---

## Task 3: Supabase state + conversation flow in the bot

**Files:**
- Modify: `Brotherhood - bot/SenPai/bot.py`

**Interfaces:**
- Consumes: `PULLUP_PLAN`, `find_starting_week`, `plan_for_week` from Task 2; `EXERCISE_CONFIG`, `rank_for_value`, `next_rank_after`, `unit_plural`, `save_exercise`, `user_id_for`, `raw_telegram_id`, `fetch_display_name`, `build_today_text`, `picker_keyboard`, `today_str`, `HEADERS`, `SUPABASE_URL` (all existing).
- Produces: `fetch_pullup_program(user_id: str) -> int | None`, `save_pullup_program(user_id: str, week: int, started_at: str = None) -> bool`, new conversation states `ASK_PULLUP_START`, `PULLUP_CONFIRM`.

This task has no automated tests (it's network I/O and Telegram callback wiring — same as the rest of the file, e.g. `save_exercise`/`fetch_history` have none either). It's verified manually at the end of the task via a live bot run against the real Supabase project from Task 1.

- [ ] **Step 1: Add the two Supabase helpers**

In `bot.py`, insert this after `fetch_history` (after line 182, before `def user_id_for` on line 185):

```python
def fetch_pullup_program(user_id: str):
    """Текущая неделя программы подтягиваний, или None если ещё не начата
    (или запрос не удался — как и fetch_display_name, эти случаи не различаются)."""
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/pullup_program",
            headers=HEADERS,
            params={"user_id": f"eq.{user_id}", "select": "current_week", "limit": 1},
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        logger.error("Supabase fetch pullup_program failed: %s", e)
        return None
    if resp.status_code >= 300:
        logger.error("Supabase fetch pullup_program error: %s %s", resp.status_code, resp.text)
        return None
    rows = resp.json()
    return rows[0]["current_week"] if rows else None


def save_pullup_program(user_id: str, week: int, started_at: str = None) -> bool:
    payload = {"user_id": user_id, "current_week": week}
    if started_at:
        payload["started_at"] = started_at
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/pullup_program",
            headers={**HEADERS, "Prefer": "resolution=merge-duplicates"},
            params={"on_conflict": "user_id"},
            json=payload,
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        logger.error("Supabase save pullup_program failed: %s", e)
        return False
    if resp.status_code >= 300:
        logger.error("Supabase save pullup_program error: %s %s", resp.status_code, resp.text)
        return False
    return True

```

- [ ] **Step 2: Add the two new conversation states**

Replace line 101:

```python
ASK_NAME, CHOOSING, ENTERING = range(3)
```

with:

```python
ASK_NAME, CHOOSING, ENTERING, ASK_PULLUP_START, PULLUP_CONFIRM = range(5)
```

- [ ] **Step 3: Add the pull-up plan text/keyboard builders and flow functions**

Insert this immediately before `async def choose_exercise_cb` (before line 370):

```python
def pullup_plan_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Сделал", callback_data="pullup:done"),
        InlineKeyboardButton("❌ Не сделал", callback_data="pullup:skip"),
    ]])


def format_pullup_plan_text(week: int) -> str:
    targets = plan_for_week(week)
    sets_line = " / ".join(str(t) for t in targets)
    header = "Неделя 30 из 30 (финал программы)" if week >= 30 else f"Неделя {week} из 30"
    return f"Подтягивания — {header}:\n{sets_line}\n\nСделал сегодня все 5 подходов?"


async def show_pullup_plan(update: Update, context: ContextTypes.DEFAULT_TYPE, week: int, edit: bool):
    context.user_data["pullup_week"] = week
    text = format_pullup_plan_text(week)
    if edit:
        await update.callback_query.edit_message_text(text, reply_markup=pullup_plan_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=pullup_plan_keyboard())
    return PULLUP_CONFIRM


async def enter_pullup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip().replace(",", ".")
    try:
        first_set = int(float(raw))
    except ValueError:
        await update.message.reply_text("Нужно число, например 8. Попробуй ещё раз.")
        return ASK_PULLUP_START

    week = find_starting_week(first_set)
    uid = user_id_for(update)
    if not save_pullup_program(uid, week, started_at=today_str()):
        await update.message.reply_text("Не получилось сохранить — попробуй ещё раз чуть позже.")
        return ConversationHandler.END

    return await show_pullup_plan(update, context, week, edit=False)


async def pullup_confirm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    done = query.data.split(":", 1)[1] == "done"
    week = context.user_data.get("pullup_week", 1)
    uid = user_id_for(update)

    if not done:
        await query.edit_message_text("Ок, повторим в следующий раз. Цели этой недели остаются прежними.")
    else:
        cfg = EXERCISE_CONFIG["pullups"]
        targets = plan_for_week(week)
        value = max(targets)

        if not save_exercise(uid, "pullups", value, cfg["unit"]):
            await query.edit_message_text("Не получилось сохранить результат — попробуй ещё раз чуть позже.")
            return CHOOSING

        next_week = min(30, week + 1)
        save_pullup_program(uid, next_week)

        rank = rank_for_value(cfg, value)
        next_name, next_bound = next_rank_after(cfg, value)
        remain = max(0, next_bound - value) if next_name else 0

        text = f"Записано: Подтягивания — {value:g}\nРазряд: {rank}"
        if remain > 0:
            text += f" · осталось {remain:g} {unit_plural(cfg)} до «{next_name}»"
        text += "\n\nПрограмма завершена 🏆" if week >= 30 else f"\n\nНеделя выросла до {next_week} из 30!"
        await query.edit_message_text(text)

    name = fetch_display_name(raw_telegram_id(update))
    await query.message.reply_text(build_today_text(uid, name), reply_markup=picker_keyboard())
    return CHOOSING


```

- [ ] **Step 4: Special-case pull-ups in `choose_exercise_cb`**

Replace the whole function body (lines 370–385):

```python
async def choose_exercise_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.split(":", 1)[1]
    context.user_data["exercise"] = key
    cfg = EXERCISE_CONFIG[key]
    prompt = f"{cfg['label']} — сколько сделал сегодня? ({cfg['unit']})"
    if cfg.get("is_ladder"):
        prompt += (
            "\n\nЕсли начал следующую ступень, но не одолел её целиком — "
            "напиши через слэш: сначала ступень, до которой дошёл полностью, "
            "потом сколько сделал на следующей. Например 8/6 — восьмая ступень "
            "пройдена, а на девятой сделал только 6."
        )
    await query.edit_message_text(prompt, reply_markup=None)
    return ENTERING
```

with:

```python
async def choose_exercise_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.split(":", 1)[1]
    context.user_data["exercise"] = key

    if key == "pullups":
        uid = user_id_for(update)
        week = fetch_pullup_program(uid)
        if week is None:
            await query.edit_message_text(
                "Сколько подтягиваний одним подходом можешь сделать сейчас? "
                "По этому числу подберём стартовую неделю программы."
            )
            return ASK_PULLUP_START
        return await show_pullup_plan(update, context, week, edit=True)

    cfg = EXERCISE_CONFIG[key]
    prompt = f"{cfg['label']} — сколько сделал сегодня? ({cfg['unit']})"
    if cfg.get("is_ladder"):
        prompt += (
            "\n\nЕсли начал следующую ступень, но не одолел её целиком — "
            "напиши через слэш: сначала ступень, до которой дошёл полностью, "
            "потом сколько сделал на следующей. Например 8/6 — восьмая ступень "
            "пройдена, а на девятой сделал только 6."
        )
    await query.edit_message_text(prompt, reply_markup=None)
    return ENTERING
```

- [ ] **Step 5: Register the new states in `today_conv`**

In `main()`, replace the `today_conv = ConversationHandler(...)` block (lines 539–563):

```python
    today_conv = ConversationHandler(
        entry_points=[
            CommandHandler("go", cmd_today),
            MessageHandler(filters.Regex(r"(?i)^на\s*сегодня\W*$"), cmd_today),
            MessageHandler(filters.Regex(r"(?i)^привет[,!]?\s+сенпай\W*$"), cmd_today),
        ],
        states={
            CHOOSING: [
                CallbackQueryHandler(choose_exercise_cb, pattern=r"^ex:"),
                CallbackQueryHandler(finish_cb, pattern=r"^done$"),
                MessageHandler(filters.Regex(f"^{COMMANDS_BUTTON_TEXT}$"), cmd_help),
            ],
            ENTERING: [
                MessageHandler(filters.Regex(f"^{COMMANDS_BUTTON_TEXT}$"), cmd_help),
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_value),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("go", cmd_today),
            MessageHandler(filters.Regex(r"(?i)^на\s*сегодня\W*$"), cmd_today),
            MessageHandler(filters.Regex(r"(?i)^привет[,!]?\s+сенпай\W*$"), cmd_today),
            CommandHandler("start", cmd_start),
        ],
    )
```

with:

```python
    today_conv = ConversationHandler(
        entry_points=[
            CommandHandler("go", cmd_today),
            MessageHandler(filters.Regex(r"(?i)^на\s*сегодня\W*$"), cmd_today),
            MessageHandler(filters.Regex(r"(?i)^привет[,!]?\s+сенпай\W*$"), cmd_today),
        ],
        states={
            CHOOSING: [
                CallbackQueryHandler(choose_exercise_cb, pattern=r"^ex:"),
                CallbackQueryHandler(finish_cb, pattern=r"^done$"),
                MessageHandler(filters.Regex(f"^{COMMANDS_BUTTON_TEXT}$"), cmd_help),
            ],
            ENTERING: [
                MessageHandler(filters.Regex(f"^{COMMANDS_BUTTON_TEXT}$"), cmd_help),
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_value),
            ],
            ASK_PULLUP_START: [
                MessageHandler(filters.Regex(f"^{COMMANDS_BUTTON_TEXT}$"), cmd_help),
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_pullup_start),
            ],
            PULLUP_CONFIRM: [
                CallbackQueryHandler(pullup_confirm_cb, pattern=r"^pullup:"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("go", cmd_today),
            MessageHandler(filters.Regex(r"(?i)^на\s*сегодня\W*$"), cmd_today),
            MessageHandler(filters.Regex(r"(?i)^привет[,!]?\s+сенпай\W*$"), cmd_today),
            CommandHandler("start", cmd_start),
        ],
    )
```

- [ ] **Step 6: Syntax-check the file**

```bash
python -m py_compile "Brotherhood - bot/SenPai/bot.py"
```

Expected: no output, exit code 0.

- [ ] **Step 7: Re-run the Task 2 unit tests (regression check)**

```bash
cd "Brotherhood - bot/SenPai" && python -m unittest test_pullup_plan.py -v
```

Expected: all 9 tests still PASS (confirms the edits didn't break the module's importability or the plan constants).

- [ ] **Step 8: Manual end-to-end verification against the real bot**

Requires: Task 1 done (table exists), and either the bot running locally (`python bot.py` from `Brotherhood - bot/SenPai/` with `TELEGRAM_BOT_TOKEN`/`SUPABASE_URL`/`SUPABASE_KEY` set to the real values from `.env`) or deployed to Railway. Test in Telegram, on an account with no existing `pullup_program` row:

1. `/go` → tap «Подтягивания» → bot asks "Сколько подтягиваний одним подходом...".
2. Reply `8` → bot shows "Неделя 3 из 30: 8 / 6 / 5 / 5 / 4" with ✅/❌ buttons (week 3 because `find_starting_week(8)` = 3, per `PULLUP_PLAN[2] == (8, 6, 5, 5, 4)`).
3. Tap ❌ Не сделал → "Ок, повторим в следующий раз" + today summary.
4. `/go` → «Подтягивания» again → shows the *same* week 3 targets (no diagnostic question this time, since the row already exists).
5. Tap ✅ Сделал → "Записано: Подтягивания — 8 ... Неделя выросла до 4 из 30!" + today summary; `/stats` now shows a "Программа: неделя 4 из 30" line under the pull-ups entry.

- [ ] **Step 9: Commit**

```bash
git add "Brotherhood - bot/SenPai/bot.py"
git commit -m "Add pull-up 5x30 program flow to SenPai bot"
```

---

## Task 4: `/stats` program line

**Files:**
- Modify: `Brotherhood - bot/SenPai/bot.py` (inside `cmd_stats`, lines 483–498)

**Interfaces:**
- Consumes: `fetch_pullup_program` from Task 3.

- [ ] **Step 1: Add the program line to `cmd_stats`**

Replace this loop body (lines 483–498):

```python
    for r in rows:
        key, cfg, history, pr, rank = r["key"], r["cfg"], r["history"], r["pr"], r["rank"]
        mark = "👉 " if key in weakest_keys else ""
        if not history:
            lines.append(f"{mark}{cfg['label']} — нет данных")
            continue
        current = float(history[-1]["value"])
        next_name, next_bound = next_rank_after(cfg, pr)
        remain = max(0, next_bound - pr) if next_name else 0
        week_count = sum(1 for h in history if h["date"] >= week_ago)

        line = f"{mark}{cfg['label']}: {current:g} {cfg['unit']} · {rank}"
        if remain > 0:
            line += f" (осталось {remain:g} {unit_plural(cfg)} до «{next_name}»)"
        line += f" · за неделю: {week_count}"
        lines.append(line)
```

with:

```python
    for r in rows:
        key, cfg, history, pr, rank = r["key"], r["cfg"], r["history"], r["pr"], r["rank"]
        mark = "👉 " if key in weakest_keys else ""
        if not history:
            lines.append(f"{mark}{cfg['label']} — нет данных")
            continue
        current = float(history[-1]["value"])
        next_name, next_bound = next_rank_after(cfg, pr)
        remain = max(0, next_bound - pr) if next_name else 0
        week_count = sum(1 for h in history if h["date"] >= week_ago)

        line = f"{mark}{cfg['label']}: {current:g} {cfg['unit']} · {rank}"
        if remain > 0:
            line += f" (осталось {remain:g} {unit_plural(cfg)} до «{next_name}»)"
        line += f" · за неделю: {week_count}"
        lines.append(line)

        if key == "pullups":
            program_week = fetch_pullup_program(uid)
            if program_week is not None:
                lines.append(
                    "  Программа: завершена 🏆" if program_week >= 30
                    else f"  Программа: неделя {program_week} из 30"
                )
```

- [ ] **Step 2: Syntax-check**

```bash
python -m py_compile "Brotherhood - bot/SenPai/bot.py"
```

Expected: no output, exit code 0.

- [ ] **Step 3: Manual verification**

Run `/stats` in Telegram on the account from Task 3 Step 8 (which now has a `pullup_program` row) and confirm the "Программа: неделя X из 30" line appears right under the pull-ups line.

- [ ] **Step 4: Commit**

```bash
git add "Brotherhood - bot/SenPai/bot.py"
git commit -m "Show pull-up program week in /stats"
```

---

## Task 5: Cabinet card — current week and targets

**Files:**
- Modify: `Brotherhood - bot/Nutrition/training.html`
- Modify: `Training-deploy/training/index.html` (kept byte-identical to the file above)

**Interfaces:**
- Consumes: existing `getUserId()`, `sbFetch()`, `EXERCISE_CONFIG`, `buildExerciseState()`, `renderTodayCard()` (all in this file).
- Produces: `PULLUP_PLAN` (JS mirror of the Python one), `pullupPlanForWeek(week)`, `fetchPullupWeek()`, `renderPullupProgramBlock(week)`.

- [ ] **Step 1: Add the JS plan constant and fetch helper**

In `Brotherhood - bot/Nutrition/training.html`, insert this immediately after the `rankIndex` function (after line 480, before the `// ── Чистые функции расчёта ──` comment on line 482):

```javascript

// Таблица прогрессии подтягиваний 5x30 — зеркало PULLUP_PLAN из SenPai/bot.py, держать в соответствии.
const PULLUP_PLAN = [
  [6,5,5,4,3],    [7,6,5,4,4],    [8,6,5,5,4],    [8,7,5,5,5],    [9,7,6,5,5],
  [10,7,6,6,5],   [10,8,6,6,6],   [11,8,7,6,6],   [12,8,7,7,6],   [12,9,7,7,7],
  [13,9,8,7,7],   [14,9,8,8,7],   [14,10,8,8,8],  [15,10,9,8,8],  [16,10,9,9,8],
  [16,11,9,9,9],  [17,11,10,9,9], [18,11,10,10,9],[18,12,10,10,10],[19,12,11,10,10],
  [20,12,11,11,10],[20,13,11,11,11],[21,13,12,11,11],[22,13,12,12,11],[22,14,12,12,12],
  [23,14,13,12,12],[24,14,13,13,12],[24,15,13,13,13],[25,15,14,13,13],[26,15,14,14,13]
];
function pullupPlanForWeek(week) {
  const w = Math.max(1, Math.min(30, week));
  return PULLUP_PLAN[w - 1];
}
async function fetchPullupWeek() {
  const uid = getUserId();
  const data = await sbFetch('GET', `/rest/v1/pullup_program?user_id=eq.${uid}&select=current_week&limit=1`);
  if (!Array.isArray(data) || !data.length) return null;
  return data[0].current_week;
}
```

- [ ] **Step 2: Fetch the current week inside `buildExerciseState`**

Replace (lines 593–598):

```javascript
async function buildExerciseState(key) {
  const cfg = EXERCISE_CONFIG[key];
  const historyAsc = await fetchExerciseHistory(key);
  if (!historyAsc.length) {
    return { cfg, key, empty: true };
  }
```

with:

```javascript
async function buildExerciseState(key) {
  const cfg = EXERCISE_CONFIG[key];
  const historyAsc = await fetchExerciseHistory(key);
  const pullupWeek = key === 'pullups' ? await fetchPullupWeek() : null;
  if (!historyAsc.length) {
    return { cfg, key, empty: true, pullupWeek };
  }
```

Then in the same function's `return` statement (line 611–614), add `pullupWeek` to the returned object:

```javascript
  return {
    cfg, key, empty: false, current, pr, target, rank, rankBound, milestone, milestoneRank,
    progressPct, last4, growthPct, trendSvg: buildTrendSvg(historyAsc), pullupWeek
  };
```

- [ ] **Step 3: Render the program block in the pull-ups card**

Add this new function immediately before `function renderTodayCard(s) {` (before line 617):

```javascript
function renderPullupProgramBlock(week) {
  if (week === null || week === undefined) return '';
  const targets = pullupPlanForWeek(week);
  const weekLbl = week >= 30 ? 'программа: неделя 30 / 30 (финал)' : `программа: неделя ${week} / 30`;
  const chips = targets.map(v => `<span class="chip">${v}</span>`).join('');
  return `
      <div class="today-ex-history">
        <div class="today-ex-history-lbl">${weekLbl}</div>
        <div class="today-ex-history-chips">${chips}</div>
      </div>`;
}

```

Then inside `renderTodayCard`, replace (lines 617–660):

```javascript
function renderTodayCard(s) {
  const { cfg, key } = s;
  if (s.empty) {
    return `<div class="today-ex-card"><div class="today-ex-main">
      <div class="today-ex-top"><span class="today-ex-name">${cfg.label}</span></div>
      <div class="today-ex-empty">Нет данных — начни с бота: пришли первый результат, чтобы запустить трекинг</div>
    </div></div>`;
  }
```

with:

```javascript
function renderTodayCard(s) {
  const { cfg, key } = s;
  const programBlock = key === 'pullups' ? renderPullupProgramBlock(s.pullupWeek) : '';
  if (s.empty) {
    return `<div class="today-ex-card"><div class="today-ex-main">
      <div class="today-ex-top"><span class="today-ex-name">${cfg.label}</span></div>
      <div class="today-ex-empty">Нет данных — начни с бота: пришли первый результат, чтобы запустить трекинг</div>
      ${programBlock}
    </div></div>`;
  }
```

And replace the closing of the non-empty card (lines 654–659):

```javascript
      <div class="today-ex-history">
        <div class="today-ex-history-lbl">последние ${s.last4.length} подхода</div>
        <div class="today-ex-history-chips">${chips}</div>
      </div>
    </div>
  </div>`;
}
```

with:

```javascript
      <div class="today-ex-history">
        <div class="today-ex-history-lbl">последние ${s.last4.length} подхода</div>
        <div class="today-ex-history-chips">${chips}</div>
      </div>
      ${programBlock}
    </div>
  </div>`;
}
```

- [ ] **Step 4: Manual browser verification**

Open `Brotherhood - bot/Nutrition/training.html` directly in a browser (file:// is fine — it already talks to the real Supabase project). Log in as the test account from Task 3 Step 8 (which has a `pullup_program` row by now). Confirm:
- The «Подтягивания» card shows an extra row below the existing history chips: "программа: неделя 4 / 30" (or whatever week that account is on) with 5 numbers matching `PULLUP_PLAN[week-1]`.
- Every other exercise card (pushups, squats, plank, ladder, bench_dips) is visually unchanged — no program block, no layout shift.
- No errors in the browser console (`read_console_messages`-style check, or just open devtools).

- [ ] **Step 5: Copy the change into the deploy mirror**

```bash
cp "Brotherhood - bot/Nutrition/training.html" "Training-deploy/training/index.html"
diff "Brotherhood - bot/Nutrition/training.html" "Training-deploy/training/index.html"
```

Expected: `diff` prints nothing (files identical).

- [ ] **Step 6: Commit**

```bash
git add "Brotherhood - bot/Nutrition/training.html" "Training-deploy/training/index.html"
git commit -m "Show pull-up 5x30 program targets in the training cabinet"
```

---

## Task 6: Deploy

Both deploys are manual per this project's existing conventions (see [project-architecture memory](../../../CLAUDE.md) and the spec) — there's no CI/CD wired for either.

- [ ] **Step 1: Confirm Task 1's Supabase table exists in production** (already done if Task 3's manual test in Step 8 passed against the real project).

- [ ] **Step 2: Push the bot changes**

```bash
git push
```

Railway is configured to deploy `Brotherhood - bot/SenPai` from this repo's `main` branch on push (per project memory) — confirm in the Railway dashboard that a new deploy started and finished without errors.

- [ ] **Step 3: Upload the cabinet file**

Manually upload the new `Brotherhood - bot/Nutrition/training.html` content to the site's `training/` folder on GitHub (same manual process already used for this file — see spec and project memory), since this repo doesn't auto-publish it.

- [ ] **Step 4: Final smoke test**

In Telegram, against the deployed bot: `/go` → «Подтягивания» on an account that has never touched the program before → confirm the diagnostic question appears, and after answering, the plan and buttons show up. Then open `nutrition.thebrotherhoodclub.com/training/` and confirm the same account's card shows the matching week/targets.
