#!/usr/bin/env python3
"""
Конвертер банка "Оценочные средства по русскому языку 1-11 классов"
(fetch_fipi.py --exam grades) в схему проекта — отдельный скрипт, не
map_schema.py, потому что источник принципиально другой:

- Нет полей "КЭС"/"Тип ответа" — только "Класс" и "Раздел" (Чтение/Письмо/
  Слушание/Говорение/Основные разделы науки о языке).
- ~99% заданий вообще без структурированного input (письмо на бумаге,
  устный ответ, оцениваются учителем) — regex-эвристики map_schema.py
  тут бесполезны, классифицировать/формулировать вопрос может только LLM.

Поэтому вся работа (решить, конвертируемо ли задание в один из 4 типов
схемы, и если да — сформулировать text/options/correct) отдана модели.
Это ЗНАЧИТЕЛЬНО менее предсказуемо по качеству, чем map_schema.py
(который просто парсит уже готовую структуру с сайта) — обязательно
выборочно проверяй результат, особенно всё с needs_review/confidence
не "high".

Секции 1-4 класса пропускаются на входе (вне диапазона схемы testy-natalia:
"5"|"6"|...|"11"|"oge"|"ege").

Использование (сначала малый прогон, оценить качество):
    python llm_convert_grades.py --in data/raw/rus_grades_raw.json \
        --out data/final/rus_grades_llm.json --limit 60
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

_thread_local = threading.local()


def get_client(timeout_sec: float) -> httpx.Client:
    """Один httpx.Client на поток пула — переиспользуется между заданиями,
    не создаётся заново на каждый запрос."""
    if not hasattr(_thread_local, "client"):
        _thread_local.client = httpx.Client(timeout=timeout_sec)
    return _thread_local.client

LEAD_PIPELINE_ENV = Path(r"E:\Работы\lead-pipeline\.env")

SYSTEM_PROMPT = (
    "Ты — эксперт по русскому языку и школьной программе. Тебе дано задание "
    "из открытого банка ФИПИ для оценки качества образования (1-11 классы). "
    "У многих таких заданий на сайте нет структурированного поля ответа — "
    "это могут быть задания \"напишите на бумаге\", устные/аудио-задания, "
    "задания с картинкой, изложения, сочинения и т.п. Твоя задача — решить, "
    "можно ли ЧЕСТНО превратить это конкретное задание в тестовый вопрос "
    "с ОДНИМ однозначным правильным ответом одного из 4 типов, и если да — "
    "сформулировать сам вопрос."
)

USER_TEMPLATE = """Верни ответ СТРОГО в виде JSON, без пояснений и текста вокруг:
{{
  "convertible": true/false,
  "type": "choice" | "sentence-number" | "word" | "digits" | null,
  "text": "..." | null,
  "passage": "..." | null,
  "options": [...] | null,
  "correct": [...] | null,
  "digit_set": true/false,
  "needs_review": true/false,
  "confidence": "high" | "medium" | "low"
}}

convertible = false, если:
- задание требует картинки/аудио/видео, которых у тебя нет (только текст ниже — если по нему не восстановить суть задания, не конвертируемо)
- задание — устный ответ, изложение, сочинение, диктант, письмо от руки без единственного правильного варианта
- невозможно сформулировать один однозначный правильный ответ

Если convertible = true:
- "text" — сама переформулированная инструкция/вопрос (кратко, по-русски)
- "passage" — прикреплённый текст/предложение, если он нужен для ответа, иначе null
- type = "choice": "options" — список вариантов, "correct" — массив с ОДНИМ индексом (с 0)
- type = "sentence-number": "correct" — массив со строкой-номером предложения, например ["2"]
- type = "word": "correct" — массив строк со всеми допустимыми вариантами ответа
- type = "digits": "correct" — массив с ОДНОЙ строкой из цифр без разделителей, например ["134"]; "digit_set" = true, если порядок цифр не важен

needs_review = true, если задание пограничное, неоднозначное, или ты не уверен в своей переформулировке.

Данные задания:
класс: {grade}
раздел: {section}
подсказка с сайта: {hint}
текст задания: {text}"""

TOOL_NAME = "convert_fipi_grades_question"
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "convertible": {"type": "boolean"},
        "type": {"type": ["string", "null"], "enum": ["choice", "sentence-number", "word", "digits", None]},
        "text": {"type": ["string", "null"]},
        "passage": {"type": ["string", "null"]},
        "options": {"type": ["array", "null"], "items": {"type": "string"}},
        "correct": {"type": ["array", "null"], "items": {"anyOf": [{"type": "integer"}, {"type": "string"}]}},
        "digit_set": {"type": "boolean"},
        "needs_review": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["convertible", "type", "text", "passage", "options", "correct",
                 "digit_set", "needs_review", "confidence"],
}

MAX_TEXT_CHARS = 3000


class LLMError(Exception):
    pass


class LLMFatalError(LLMError):
    pass


def load_lead_pipeline_env() -> dict:
    if not LEAD_PIPELINE_ENV.exists():
        raise SystemExit(f"Не найден {LEAD_PIPELINE_ENV} — там ключи Токенатора")
    env = {}
    for line in LEAD_PIPELINE_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def grade_number(grade_label: str | None) -> int | None:
    if not grade_label:
        return None
    m = re.match(r"\s*(\d+)", grade_label)
    return int(m.group(1)) if m else None


def render_user_prompt(rec: dict) -> str:
    text = rec.get("question_text") or ""
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + f" … [обрезано, всего {len(rec['question_text'])} симв.]"
    return USER_TEMPLATE.format(
        grade=rec.get("grade_label") or "?",
        section=rec.get("section_label") or "?",
        hint=rec.get("hint") or "нет",
        text=text or "(пусто)",
    )


def _extract_json(content: str):
    content = content.strip()
    content = re.sub(r"^```[a-zA-Z]*\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    start, end = content.find("{"), content.rfind("}")
    if start != -1 and end > start:
        return json.loads(content[start:end + 1])
    raise LLMError(f"в ответе нет JSON: {content[:200]!r}")


def call_llm(client: httpx.Client, base_url: str, api_key: str, model: str,
             max_tokens: int, rec: dict) -> dict:
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": render_user_prompt(rec)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": TOOL_NAME, "strict": True, "schema": TOOL_SCHEMA},
        },
        "temperature": 0,
        "thinking": {"type": "disabled"},
    }
    try:
        r = client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
    except httpx.TimeoutException as e:
        raise LLMError(f"таймаут: {e}") from e
    except httpx.HTTPError as e:
        raise LLMError(f"сеть: {type(e).__name__}: {e}") from e

    if r.status_code in (401, 403, 404):
        raise LLMFatalError(f"HTTP {r.status_code}: {r.text[:300]}")
    if r.status_code != 200:
        raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")

    try:
        body = r.json()
        content = body["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
        raise LLMError(f"неожиданный формат ответа: {e}: {r.text[:300]}") from e
    if not content or not content.strip():
        raise LLMError(f"модель вернула пустой content: {r.text[:300]}")
    return _extract_json(content)


def build_final_item(rec: dict, answer: dict) -> dict | None:
    if not answer.get("convertible"):
        return None
    qtype = answer.get("type")
    if qtype not in ("choice", "sentence-number", "word", "digits"):
        return None
    text = (answer.get("text") or "").strip()
    if not text:
        return None

    grade = grade_number(rec.get("grade_label"))
    section = str(grade) if grade else None

    correct = answer.get("correct") or []
    if qtype == "choice":
        options = answer.get("options") or []
        try:
            correct = [int(correct[0])] if correct else []
        except (TypeError, ValueError):
            correct = []
        needs_review = answer.get("needs_review", True) or not correct or not (0 <= correct[0] < len(options))
    else:
        options = None
        correct = [str(c) for c in correct]
        needs_review = bool(answer.get("needs_review", True)) or not correct

    return {
        "section": section,
        "topic": rec.get("section_label") or "Без темы",
        "level": 1 if grade and grade <= 6 else (2 if grade and grade <= 9 else 3),
        "test_title": f"{rec.get('grade_label') or '?'}. Русский язык — {rec.get('section_label') or ''}".strip(),
        "type": qtype,
        "text": text,
        "passage": answer.get("passage") or None,
        "options": options,
        "hint": None,
        "correct": correct,
        "digit_set": bool(answer.get("digit_set", False)),
        "needs_review": needs_review,
        "_source_guid": rec.get("guid"),
        "_source_short_id": rec.get("short_id"),
        "_source_exam": "grades",
        "_llm_confidence": answer.get("confidence", "low"),
        "_llm_model": None,  # заполняется в process()
    }


def load_eligible(records: list[dict]) -> list[dict]:
    return [r for r in records if (grade_number(r.get("grade_label")) or 0) in range(5, 12)
            and r.get("question_text")]


def process_one(rec: dict, base_url: str, api_key: str, model: str, max_tokens: int,
                 timeout_sec: float, max_attempts: int, delay_sec: float) -> tuple[str, dict, dict | None, str | None]:
    """Выполняется в потоке пула. Возвращает (status, rec, item_or_None, error_or_None)."""
    client = get_client(timeout_sec)
    attempt = 0
    while True:
        attempt += 1
        try:
            answer = call_llm(client, base_url, api_key, model, max_tokens, rec)
            item = build_final_item(rec, answer)
            if item is not None:
                item["_llm_model"] = model
            return ("ok", rec, item, None)
        except LLMFatalError as e:
            return ("fatal", rec, None, str(e))
        except LLMError as e:
            if attempt >= max_attempts:
                return ("error", rec, None, str(e))
            time.sleep(delay_sec * (2 ** (attempt - 1)))


def process(records: list[dict], limit: int, out_path: Path, seen_path: Path, base_url: str,
            api_key: str, model: str, max_tokens: int, timeout_sec: float, max_attempts: int,
            delay_sec: float, workers: int, checkpoint_every: int,
            results: list[dict], seen_guids: set, stats: dict) -> None:
    """Параллельно (ThreadPoolExecutor) обрабатывает eligible-записи, которых
    ещё нет в seen_guids (обработанные ранее — как успешно сконвертированные,
    так и признанные неконвертируемыми, иначе резюме будет бесконечно платить
    за повторную проверку одного и того же "не подходит"), и периодически
    сохраняет накопленное в out_path/seen_path, чтобы обрыв на середине
    не стоил всех уже оплаченных LLM-вызовов."""
    eligible = load_eligible(records)
    to_process = [r for r in eligible if r.get("guid") not in seen_guids][:limit]
    if not to_process:
        return

    lock = threading.Lock()
    fatal_holder = {"error": None}
    since_checkpoint = 0
    done_count = 0

    def save():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        seen_path.write_text(json.dumps(sorted(seen_guids)), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(process_one, rec, base_url, api_key, model, max_tokens,
                             timeout_sec, max_attempts, delay_sec): rec
            for rec in to_process
        }
        for future in as_completed(futures):
            status, rec, item, err = future.result()
            with lock:
                done_count += 1
                since_checkpoint += 1
                if status == "fatal":
                    fatal_holder["error"] = err
                    stats["errors"] += 1
                    print(f"ФАТАЛЬНАЯ ОШИБКА: {err}", file=sys.stderr)
                elif status == "error":
                    stats["errors"] += 1
                    print(f"[{done_count}/{len(to_process)}] {rec['short_id']}: сдаюсь: {err}", file=sys.stderr)
                else:
                    stats["seen"] += 1
                    seen_guids.add(rec["guid"])
                    if item is None:
                        stats["not_convertible"] += 1
                        print(f"[{done_count}/{len(to_process)}] {rec['short_id']}: не конвертируемо",
                              file=sys.stderr)
                    else:
                        results.append(item)
                        stats["converted"] += 1
                        if item["needs_review"]:
                            stats["needs_review"] += 1
                        print(f"[{done_count}/{len(to_process)}] {rec['short_id']}: type={item['type']} "
                              f"correct={item['correct']} review={item['needs_review']} "
                              f"conf={item['_llm_confidence']}", file=sys.stderr)
                if since_checkpoint >= checkpoint_every:
                    save()
                    since_checkpoint = 0
            if fatal_holder["error"]:
                for f in futures:
                    f.cancel()
                break

    with lock:
        save()
    if fatal_holder["error"]:
        raise SystemExit(f"Остановлено из-за фатальной ошибки: {fatal_holder['error']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="inp", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--model", default="deepseek-v4.1-flash")
    parser.add_argument("--base-url", default="https://api.tokenator.top/v1")
    parser.add_argument("--max-tokens", type=int, default=1500)
    parser.add_argument("--delay", type=float, default=0.3,
                         help="пауза перед повтором на ошибку (backoff), не между обычными запросами")
    parser.add_argument("--workers", type=int, default=8, help="сколько запросов слать параллельно")
    parser.add_argument("--checkpoint-every", type=int, default=25,
                         help="сохранять --out на диск раз в столько обработанных заданий")
    args = parser.parse_args()

    env = load_lead_pipeline_env()
    api_key = env["LLM_API_KEY"]
    timeout_sec = float(env.get("LLM_TIMEOUT_SEC", 180))
    max_attempts = int(env.get("LLM_MAX_ATTEMPTS", 4))

    records = json.loads(args.inp.read_text(encoding="utf-8"))
    stats = {"seen": 0, "converted": 0, "not_convertible": 0, "needs_review": 0, "errors": 0}

    seen_path = args.out.with_suffix(".seen.json")
    results: list[dict] = []
    seen_guids: set = set()
    if args.out.exists():
        try:
            results = json.loads(args.out.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"{args.out} повреждён, начинаю заново", file=sys.stderr)
    if seen_path.exists():
        try:
            seen_guids = set(json.loads(seen_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    if seen_guids:
        print(f"Резюме: {len(seen_guids)} заданий уже обработано ({len(results)} конвертировано) "
              f"— пропускаю их", file=sys.stderr)

    print(f"Смоук-тест на 1 задании (model={args.model})...", file=sys.stderr)
    process(records, 1, args.out, seen_path, args.base_url, api_key, args.model, args.max_tokens,
            timeout_sec, 1, args.delay, 1, 1, results, seen_guids, stats)
    if stats["errors"]:
        raise SystemExit("Смоук-тест не прошёл, дальше не продолжаю.")
    print(f"Смоук-тест ок, обрабатываю остальное ({args.workers} параллельных запросов)...", file=sys.stderr)

    process(records, args.limit - 1, args.out, seen_path, args.base_url, api_key, args.model, args.max_tokens,
            timeout_sec, max_attempts, args.delay, args.workers, args.checkpoint_every, results, seen_guids, stats)

    print(f"\nОбработано: {stats['seen']}, конвертировано: {stats['converted']} "
          f"(needs_review={stats['needs_review']}), не конвертируемо: {stats['not_convertible']}, "
          f"ошибок: {stats['errors']} -> {args.out} (всего в файле: {len(results)})", file=sys.stderr)


if __name__ == "__main__":
    main()
