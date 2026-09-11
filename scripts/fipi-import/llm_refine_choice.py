#!/usr/bin/env python3
"""
Доразбор choice-заданий с needs_review=true: часть из них на самом деле
"выберите 2 из 5" (или больше), а наша схема хранит только один индекс в
correct — из-за этого модель на шаге llm_answer.py/llm_convert_grades.py
не может дать честный полный ответ и просит needs_review.

Прогоняет DeepSeek ещё раз ТОЛЬКО по записям type="choice" и
needs_review=true, просит модель явно решить: один ответ или несколько,
и если несколько — обновляет type на "multi-choice" и correct на список
ВСЕХ верных индексов. needs_review пересчитывается заново по новому
ответу (не остаётся true автоматически).

ВАЖНО: "multi-choice" — новый тип, которого нет в CHECK-констрейнте
supabase/schema.sql (там только choice/sentence-number/word/digits).
Это осознанно — сначала размечаем данные верно, схему/checker.js под
multi-choice дорабатывать отдельно, если понадобится в БД.

Использование:
    python llm_refine_choice.py --in data/final/rus_final_llm.json
    python llm_refine_choice.py --in data/final/rus_grades_llm.json
(перезаписывает --in на месте, с чекпоинтами и резюме — как llm_convert_grades.py)
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

LEAD_PIPELINE_ENV = Path(r"E:\Работы\lead-pipeline\.env")

SYSTEM_PROMPT = "Ты — эксперт по русскому языку. Тебе дано задание с вариантами ответа. Определи:"

USER_TEMPLATE = """Ты — эксперт по русскому языку. Тебе дано задание с вариантами ответа. Определи:
1) нужно выбрать ОДИН правильный вариант, или НЕСКОЛЬКО (ищи в тексте задания подсказки: "укажите цифру" (ед.ч.) — обычно один; "укажите цифры", "два", "несколько", "все верные варианты" (мн.ч.) — обычно несколько)
2) сам(и) правильный(е) вариант(ы)

Верни СТРОГО JSON без пояснений:
{{
  "type": "choice" | "multi-choice",
  "correct": [индекс] | [индекс1, индекс2, ...],
  "needs_review": true/false,
  "confidence": "high" | "medium" | "low"
}}

"choice" — если ответ один, correct содержит один индекс.
"multi-choice" — если ответов несколько, correct содержит ВСЕ правильные индексы.
needs_review = true, если из текста задания непонятно, сколько ответов нужно, или задание в принципе странное/неполное.

Данные задания:
text: {text}
passage: {passage}
options: {options}"""

TOOL_NAME = "refine_choice_question"
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["choice", "multi-choice"]},
        "correct": {"type": "array", "items": {"type": "integer"}},
        "needs_review": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["type", "correct", "needs_review", "confidence"],
}

_thread_local = threading.local()


def get_client(timeout_sec: float) -> httpx.Client:
    if not hasattr(_thread_local, "client"):
        _thread_local.client = httpx.Client(timeout=timeout_sec)
    return _thread_local.client


class LLMError(Exception):
    pass


class LLMFatalError(LLMError):
    pass


class RateLimitError(LLMError):
    def __init__(self, message: str, retry_after: float):
        super().__init__(message)
        self.retry_after = retry_after


def load_lead_pipeline_env() -> dict:
    env = {}
    for line in LEAD_PIPELINE_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def render_user_prompt(item: dict) -> str:
    options = item.get("options") or []
    return USER_TEMPLATE.format(
        text=item.get("text") or "",
        passage=item.get("passage") or "нет",
        options=json.dumps(options, ensure_ascii=False),
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
        try:
            return json.loads(content[start:end + 1])
        except json.JSONDecodeError as e:
            raise LLMError(f"невалидный JSON в ответе: {e}: {content[:300]!r}") from e
    raise LLMError(f"в ответе нет JSON: {content[:200]!r}")


def call_llm(client: httpx.Client, base_url: str, api_key: str, model: str,
             max_tokens: int, item: dict) -> dict:
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": render_user_prompt(item)},
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
    if r.status_code == 429:
        retry_after = 5.0
        try:
            retry_after = float(r.json()["error"]["retry_after_seconds"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass
        raise RateLimitError(f"HTTP 429: {r.text[:200]}", retry_after)
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


def apply_answer(item: dict, answer: dict) -> None:
    options = item.get("options") or []
    correct = answer.get("correct") or []
    correct = [c for c in (int(x) for x in correct if isinstance(x, (int, float)) or str(x).lstrip("-").isdigit())
               if 0 <= c < len(options)]
    new_type = answer.get("type")
    if new_type not in ("choice", "multi-choice"):
        new_type = "choice"
    if new_type == "choice" and len(correct) > 1:
        new_type = "multi-choice"  # модель сама себе противоречит — доверяем списку индексов
    needs_review = bool(answer.get("needs_review", True)) or not correct
    item["type"] = new_type
    item["correct"] = correct
    item["needs_review"] = needs_review
    item["_llm_confidence"] = answer.get("confidence", "low")
    item["_llm_refined"] = True


def process_one(item: dict, base_url: str, api_key: str, model: str, max_tokens: int,
                 timeout_sec: float, max_attempts: int, delay_sec: float) -> tuple[str, dict, dict | None, str | None]:
    client = get_client(timeout_sec)
    attempt = 0
    while True:
        attempt += 1
        try:
            answer = call_llm(client, base_url, api_key, model, max_tokens, item)
            return ("ok", item, answer, None)
        except LLMFatalError as e:
            return ("fatal", item, None, str(e))
        except RateLimitError as e:
            if attempt >= max_attempts:
                return ("error", item, None, str(e))
            time.sleep(min(e.retry_after + 1, 60))
        except LLMError as e:
            if attempt >= max_attempts:
                return ("error", item, None, str(e))
            time.sleep(delay_sec * (2 ** (attempt - 1)))
        except Exception as e:
            if attempt >= max_attempts:
                return ("error", item, None, f"{type(e).__name__}: {e}")
            time.sleep(delay_sec * (2 ** (attempt - 1)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="inp", required=True, type=Path)
    parser.add_argument("--model", default="deepseek-v4.1-flash")
    parser.add_argument("--base-url", default="https://api.tokenator.top/v1")
    parser.add_argument("--max-tokens", type=int, default=800)
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    args = parser.parse_args()

    env = load_lead_pipeline_env()
    api_key = env["LLM_API_KEY"]
    timeout_sec = float(env.get("LLM_TIMEOUT_SEC", 180))
    max_attempts = int(env.get("LLM_MAX_ATTEMPTS", 4))

    data = json.loads(args.inp.read_text(encoding="utf-8"))
    targets = [d for d in data if d.get("type") == "choice" and d.get("needs_review")
               and not d.get("_llm_refined")]
    print(f"Целей на доразбор: {len(targets)} (из {sum(1 for d in data if d.get('type')=='choice')} choice)",
          file=sys.stderr)
    if not targets:
        return

    lock = threading.Lock()
    fatal_holder = {"error": None}
    since_checkpoint = 0
    done_count = 0
    stats = {"multi": 0, "still_choice": 0, "still_review": 0, "errors": 0}

    def save():
        args.inp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(process_one, item, args.base_url, api_key, args.model, args.max_tokens,
                             timeout_sec, max_attempts, args.delay): item
            for item in targets
        }
        for future in as_completed(futures):
            status, item, answer, err = future.result()
            with lock:
                done_count += 1
                since_checkpoint += 1
                if status == "fatal":
                    fatal_holder["error"] = err
                    stats["errors"] += 1
                    print(f"ФАТАЛЬНАЯ ОШИБКА: {err}", file=sys.stderr)
                elif status == "error":
                    stats["errors"] += 1
                    print(f"[{done_count}/{len(targets)}] {item.get('_source_short_id')}: сдаюсь: {err}",
                          file=sys.stderr)
                else:
                    apply_answer(item, answer)
                    if item["type"] == "multi-choice":
                        stats["multi"] += 1
                    else:
                        stats["still_choice"] += 1
                    if item["needs_review"]:
                        stats["still_review"] += 1
                    print(f"[{done_count}/{len(targets)}] {item.get('_source_short_id')}: "
                          f"type={item['type']} correct={item['correct']} review={item['needs_review']}",
                          file=sys.stderr)
                if since_checkpoint >= args.checkpoint_every:
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

    print(f"\nГотово: multi-choice={stats['multi']}, остались choice={stats['still_choice']} "
          f"(из них ещё needs_review={stats['still_review']}), ошибок={stats['errors']} -> {args.inp}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
