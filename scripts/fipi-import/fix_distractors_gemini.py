#!/usr/bin/env python3
"""
Переписывает дистракторы (неверные варианты ответа) у choice/multi-choice
заданий банка классов 5-11 — они были СГЕНЕРИРОВАНЫ моделью с нуля на
шаге конвертации и часто оказывались случайными обрывками исходного
текста вместо правдоподобных ложных вариантов (см. обсуждение в сессии —
пример "какое сравнение..." с дистракторами "словно шутя"/"с крепким
клювом", вообще не про цвет).

Модель — gemini-3.8-flash с reasoning_effort=none (не thinking:disabled —
тот параметр специфичен для DeepSeek и Gemini не слушается; reasoning_effort
подтверждён рабочим и вдвое дешевле дефолтного thinking-режима).

Использование:
    python fix_distractors_gemini.py --in data/final/rus_grades_llm.json \
        --raw data/raw_v2/rus_grades_raw.json
(перезаписывает --in на месте, с чекпоинтами и резюме)
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

SYSTEM_PROMPT = (
    "Ты — опытный методист, составляющий тестовые задания по русскому "
    "языку для школьников (5-11 класс). Тебе дано задание закрытого типа "
    "(с вариантами ответа). Текущие варианты могут быть неудачными — "
    "случайными обрывками исходного текста, а не полноценными "
    "дистракторами. Твоя задача — переработать варианты ответа так, "
    "чтобы задание стало полноценным тестом."
)

USER_TEMPLATE = """Оригинальный текст задания (с сайта ФИПИ, до разбора): {raw_text}
Текущая формулировка вопроса: {text}
Текущие варианты: {options}
Текущий(е) правильный(е) ответ(ы) по индексу: {correct}

Переработай варианты ответа по правилам:
1. Правильный(е) вариант(ы) должен остаться по смыслу верным — не меняй сам факт, что это правильный ответ.
2. Остальные варианты (дистракторы) перепиши — каждый должен:
   - относиться к той же категории/теме, что и правильный ответ (не быть очевидно посторонним обрывком текста)
   - быть правдоподобным — не отсеиваться с первого взгляда, требовать понимания материала
   - быть грамматически однородным с другими вариантами
3. Сохрани то же количество вариантов и тот же тип (choice — один верный, multi-choice — несколько).
4. Если по имеющимся данным невозможно придумать качественные дистракторы (слишком мало контекста) — честно скажи об этом (needs_review: true), не сочиняй абы что.
5. Если текущие варианты уже хорошие — не переписывай их просто ради переписывания, верни как есть.

Верни СТРОГО JSON:
{{"options": [...], "correct": [...], "needs_review": true/false, "confidence": "high"|"medium"|"low"}}"""

TOOL_NAME = "fix_distractors"
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "options": {"type": "array", "items": {"type": "string"}},
        "correct": {"type": "array", "items": {"type": "integer"}},
        "needs_review": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["options", "correct", "needs_review", "confidence"],
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


def render_user_prompt(item: dict, raw_text: str) -> str:
    return USER_TEMPLATE.format(
        raw_text=raw_text or "(нет)",
        text=item["text"],
        options=json.dumps(item.get("options") or [], ensure_ascii=False),
        correct=item.get("correct") or [],
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
            raise LLMError(f"невалидный JSON: {e}: {content[:300]!r}") from e
    raise LLMError(f"в ответе нет JSON: {content[:200]!r}")


def call_llm(client: httpx.Client, base_url: str, api_key: str, model: str,
             max_tokens: int, item: dict, raw_text: str) -> dict:
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": render_user_prompt(item, raw_text)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": TOOL_NAME, "strict": True, "schema": TOOL_SCHEMA},
        },
        "temperature": 0,
        "reasoning_effort": "none",
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
    options = answer.get("options") or []
    correct = [c for c in (answer.get("correct") or []) if isinstance(c, int) and 0 <= c < len(options)]
    item["options"] = options
    if correct:
        item["correct"] = correct
        if len(correct) > 1 and item["type"] == "choice":
            item["type"] = "multi-choice"
        elif len(correct) == 1 and item["type"] == "multi-choice":
            item["type"] = "choice"
    item["needs_review"] = bool(answer.get("needs_review", True)) or not correct
    item["_llm_confidence"] = answer.get("confidence", "low")
    item["_distractors_fixed"] = True


def process_one(item: dict, raw_text: str, base_url: str, api_key: str, model: str, max_tokens: int,
                 timeout_sec: float, max_attempts: int, delay_sec: float) -> tuple[str, dict, str | None]:
    client = get_client(timeout_sec)
    attempt = 0
    while True:
        attempt += 1
        try:
            answer = call_llm(client, base_url, api_key, model, max_tokens, item, raw_text)
            apply_answer(item, answer)
            return ("ok", item, None)
        except LLMFatalError as e:
            return ("fatal", item, str(e))
        except RateLimitError as e:
            if attempt >= max_attempts:
                return ("error", item, str(e))
            time.sleep(min(e.retry_after + 1, 60))
        except LLMError as e:
            if attempt >= max_attempts:
                return ("error", item, str(e))
            time.sleep(delay_sec * (2 ** (attempt - 1)))
        except Exception as e:
            if attempt >= max_attempts:
                return ("error", item, f"{type(e).__name__}: {e}")
            time.sleep(delay_sec * (2 ** (attempt - 1)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="inp", required=True, type=Path)
    parser.add_argument("--raw", required=True, type=Path)
    parser.add_argument("--model", default="gemini-3.8-flash")
    parser.add_argument("--base-url", default="https://api.tokenator.top/v1")
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--checkpoint-every", type=int, default=20)
    args = parser.parse_args()

    env = load_lead_pipeline_env()
    api_key = env["LLM_API_KEY"]
    timeout_sec = float(env.get("LLM_TIMEOUT_SEC", 180))
    max_attempts = int(env.get("LLM_MAX_ATTEMPTS", 4))

    data = json.loads(args.inp.read_text(encoding="utf-8"))
    raw_by_guid = {r["guid"]: r for r in json.loads(args.raw.read_text(encoding="utf-8")) if r.get("guid")}

    targets = [d for d in data if d.get("type") in ("choice", "multi-choice") and not d.get("_distractors_fixed")]
    print(f"Целей: {len(targets)}", file=sys.stderr)
    if not targets:
        return

    lock = threading.Lock()
    fatal_holder = {"error": None}
    since_checkpoint = 0
    done_count = 0
    stats = {"ok": 0, "errors": 0}

    def save():
        args.inp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(process_one, item, raw_by_guid.get(item.get("_source_guid"), {}).get("question_text", ""),
                             args.base_url, api_key, args.model, args.max_tokens,
                             timeout_sec, max_attempts, args.delay): item
            for item in targets
        }
        for future in as_completed(futures):
            status, item, err = future.result()
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
                    stats["ok"] += 1
                    print(f"[{done_count}/{len(targets)}] {item.get('_source_short_id')}: "
                          f"type={item['type']} review={item['needs_review']}", file=sys.stderr)
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
        raise SystemExit(f"Остановлено: {fatal_holder['error']}")

    print(f"\nГотово: ok={stats['ok']}, ошибок={stats['errors']} -> {args.inp}", file=sys.stderr)


if __name__ == "__main__":
    main()
