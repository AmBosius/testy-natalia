#!/usr/bin/env python3
"""
Шаг 4 (доп.): заполняет "correct" для заданий, размеченных map_schema.py,
через LLM — сам ФИПИ ответы не публикует (см. map_schema.py), поэтому их
определяет модель по правилам русского языка.

Использует тот же прокси, что и E:\\Работы\\lead-pipeline (Токенатор):
ключ берётся из E:\\Работы\\lead-pipeline\\.env (LLM_API_KEY), но модель
для этой задачи — дешёвая/быстрая (DeepSeek/Qwen), не Claude: объём
механический (1000+ заданий). Для не-Anthropic моделей у Токенатора
нужен OpenAI-совместимый путь /chat/completions на отдельном базовом
URL (https://api.tokenator.top/v1), а не Anthropic /v1/messages на
.../anthropic из LLM_BASE_URL — тот отдаёт 503 на любую не-Claude модель
(проверено даже на заведомо несуществующей — это generic "недоступна",
а не хинт про имя). Тот же паттерн разделения openai/anthropic путей,
что в app/qualify/llm.py у lead-pipeline.

Использование:
    python llm_answer.py --in data/final/rus_final.json \
        --out data/final/rus_final_llm.json --limit 80
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx

LEAD_PIPELINE_ENV = Path(r"E:\Работы\lead-pipeline\.env")

SYSTEM_PROMPT = (
    "Ты — эксперт по русскому языку и школьной программе. Тебе дано одно "
    "задание по русскому языку. Определи правильный ответ строго по "
    "правилам грамматики."
)

USER_TEMPLATE = """Верни ответ СТРОГО в виде JSON, без пояснений и текста вокруг:
{{
  "correct": [...],
  "needs_review": true/false,
  "confidence": "high" | "medium" | "low"
}}

Правила заполнения "correct":
- если type = "choice" — массив с ОДНИМ числом: индекс правильного варианта, начиная с 0
- если type = "sentence-number" — массив со строкой-номером предложения, например ["2"]
- если type = "word" — массив строк со всеми допустимыми вариантами ответа
- если type = "digits" — массив с ОДНОЙ строкой из цифр без разделителей, например ["134"]

needs_review = true, если задание неоднозначное, в тексте опечатка/ошибка, не хватает данных, или ты не уверен в ответе.

Данные задания:
type: {type}
text: {text}
passage: {passage}
options: {options}"""

TOOL_NAME = "answer_fipi_question"
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "correct": {
            "type": "array",
            "items": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
        },
        "needs_review": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["correct", "needs_review", "confidence"],
}


class LLMError(Exception):
    """Сеть/таймаут/5xx/429 — имеет смысл повторить."""


class LLMFatalError(LLMError):
    """Неверный ключ/модель/права — повтор не поможет, нужно чинить конфиг."""


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


def render_user_prompt(item: dict) -> str:
    options = item.get("options")
    options_str = json.dumps(options, ensure_ascii=False) if options else "нет"
    passage_str = item.get("passage") or "нет"
    return USER_TEMPLATE.format(
        type=item["type"], text=item["text"], passage=passage_str, options=options_str
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


def call_llm(client: httpx.Client, base_url: str, api_key: str,
             model: str, max_tokens: int, item: dict) -> dict:
    """OpenAI-совместимый путь (/chat/completions + response_format json_schema) —
    именно он у Токенатора нужен для роутеров вроде DeepSeek/Qwen (не Anthropic
    /v1/messages), см. E:\\Работы\\lead-pipeline\\.env.example."""
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
        # DeepSeek думает по умолчанию (effort=high) — для механической
        # разметки это лишнее время и лишние токены, выключаем.
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


def validate_answer(item: dict, answer: dict) -> tuple[list, bool, str]:
    """Подстраховка поверх ответа модели: если она сама себя не проверила
    (индекс за пределами options, странный тип и т.п.) — форсируем needs_review."""
    correct = answer.get("correct")
    needs_review = bool(answer.get("needs_review", True))
    confidence = answer.get("confidence", "low")

    if not isinstance(correct, list) or not correct:
        return [], True, "low"

    qtype = item["type"]
    if qtype == "choice":
        options = item.get("options") or []
        try:
            idx = int(correct[0])
        except (TypeError, ValueError):
            return [], True, confidence
        if idx < 0 or idx >= len(options):
            return [idx], True, confidence
        return [idx], needs_review, confidence

    # sentence-number / word / digits — ожидаем строки
    fixed = [str(c) for c in correct]
    return fixed, needs_review, confidence


def process(items: list[dict], limit: int, base_url: str, api_key: str,
            model: str, max_tokens: int,
            timeout_sec: float, max_attempts: int, delay_sec: float) -> dict:
    stats = {"ok": 0, "needs_review_forced": 0, "errors": 0}
    to_process = [it for it in items if it["type"] in ("choice", "sentence-number", "word", "digits")][:limit]

    with httpx.Client(timeout=timeout_sec) as client:
        for i, item in enumerate(to_process, 1):
            attempt = 0
            while True:
                attempt += 1
                try:
                    answer = call_llm(client, base_url, api_key, model, max_tokens, item)
                    correct, needs_review, confidence = validate_answer(item, answer)
                    item["correct"] = correct
                    item["needs_review"] = needs_review
                    item["_llm_confidence"] = confidence
                    item["_llm_model"] = model
                    stats["ok"] += 1
                    if needs_review:
                        stats["needs_review_forced"] += 1
                    print(f"[{i}/{len(to_process)}] {item['_source_short_id']}: "
                          f"correct={correct} review={needs_review} conf={confidence}", file=sys.stderr)
                    break
                except LLMFatalError as e:
                    print(f"ФАТАЛЬНАЯ ОШИБКА (проверь --model/ключ в .env): {e}", file=sys.stderr)
                    stats["errors"] += 1
                    return stats
                except LLMError as e:
                    if attempt >= max_attempts:
                        print(f"[{i}/{len(to_process)}] {item['_source_short_id']}: "
                              f"сдаюсь после {attempt} попыток: {e}", file=sys.stderr)
                        stats["errors"] += 1
                        break
                    backoff = delay_sec * (2 ** (attempt - 1))
                    print(f"[{i}/{len(to_process)}] попытка {attempt} не удалась ({e}), "
                          f"жду {backoff:.1f}с", file=sys.stderr)
                    time.sleep(backoff)
            time.sleep(delay_sec)

    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="inp", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=80, help="сколько заданий обработать за прогон")
    parser.add_argument("--model", default="deepseek-v4.1-flash",
                         help="model id в каталоге Токенатора (дефолт — DeepSeek V4.1 Flash)")
    parser.add_argument("--base-url", default="https://api.tokenator.top/v1",
                         help="OpenAI-совместимый эндпоинт Токенатора (не /anthropic — тот только для Claude)")
    parser.add_argument("--max-tokens", type=int, default=4096,
                         help="DeepSeek — reasoning-модель, часть токенов уходит в цепочку рассуждений")
    parser.add_argument("--delay", type=float, default=0.3, help="пауза между запросами, сек")
    args = parser.parse_args()

    env = load_lead_pipeline_env()
    api_key = env["LLM_API_KEY"]
    timeout_sec = float(env.get("LLM_TIMEOUT_SEC", 180))
    max_attempts = int(env.get("LLM_MAX_ATTEMPTS", 4))

    items = json.loads(args.inp.read_text(encoding="utf-8"))

    print(f"Смоук-тест на 1 задании (model={args.model}, base_url={args.base_url})...", file=sys.stderr)
    smoke_stats = process(items, 1, args.base_url, api_key,
                           args.model, args.max_tokens, timeout_sec, 1, args.delay)
    if smoke_stats["errors"]:
        raise SystemExit(
            "Смоук-тест не прошёл — проверь --model/--base-url (каталог моделей "
            "прокси) и ключ в lead-pipeline/.env, дальше не продолжаю."
        )
    print("Смоук-тест ок, обрабатываю остальное...", file=sys.stderr)

    remaining = [it for it in items if "_llm_model" not in it]
    stats = process(remaining, args.limit - 1, args.base_url, api_key,
                     args.model, args.max_tokens, timeout_sec, max_attempts, args.delay)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    total_ok = smoke_stats["ok"] + stats["ok"]
    total_errors = smoke_stats["errors"] + stats["errors"]
    total_review = smoke_stats["needs_review_forced"] + stats["needs_review_forced"]
    print(f"\nГотово: {total_ok} размечено, из них needs_review={total_review}, "
          f"ошибок={total_errors} -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
