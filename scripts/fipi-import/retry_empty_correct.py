#!/usr/bin/env python3
"""
Точечно передёргивает задания с пустым correct: [] — это не обязательно
"модель не знает ответ", это может быть технический хвост с прошлых
прогонов (до фикса обработки 429 rate-limit — тогда 4 попытки с коротким
бэкоффом не успевали дождаться нужных 25 секунд и падали в пустышку).

Раз ретрай починен — эти задания стоит спросить ещё раз тем же промптом,
которым их размечали изначально (llm_answer.py для choice/word/digits/
sentence-number, llm_refine_choice.py для multi-choice), а не сразу
сдаваться в needs_review.

Задания с НЕПУСТЫМ correct, но низкой confidence — не трогает: там модель
уже дала ответ и сама сказала, что не уверена, переспрашивать то же самое
бессмысленно.

Использование:
    python retry_empty_correct.py --in data/final/rus_final_llm.json
    python retry_empty_correct.py --in data/final/rus_grades_llm.json
(перезаписывает --in на месте, с чекпоинтами)
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

import llm_answer
import llm_refine_choice

LEAD_PIPELINE_ENV = Path(r"E:\Работы\lead-pipeline\.env")

_thread_local = threading.local()


def get_client(timeout_sec: float) -> httpx.Client:
    if not hasattr(_thread_local, "client"):
        _thread_local.client = httpx.Client(timeout=timeout_sec)
    return _thread_local.client


def load_lead_pipeline_env() -> dict:
    env = {}
    for line in LEAD_PIPELINE_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def retry_one(item: dict, base_url: str, api_key: str, model: str, max_tokens: int,
              timeout_sec: float, max_attempts: int, delay_sec: float) -> tuple[str, dict, str | None]:
    """Возвращает (status, item, error). Мутирует item на месте при успехе."""
    client = get_client(timeout_sec)
    is_multi = item.get("type") == "multi-choice"
    attempt = 0
    while True:
        attempt += 1
        try:
            if is_multi:
                answer = llm_refine_choice.call_llm(client, base_url, api_key, model, max_tokens, item)
                llm_refine_choice.apply_answer(item, answer)
            else:
                answer = llm_answer.call_llm(client, base_url, api_key, model, max_tokens, item)
                correct, needs_review, confidence = llm_answer.validate_answer(item, answer)
                item["correct"] = correct
                item["needs_review"] = needs_review
                item["_llm_confidence"] = confidence
            item["_retried_empty"] = True
            return ("ok", item, None)
        except (llm_answer.LLMFatalError, llm_refine_choice.LLMFatalError) as e:
            return ("fatal", item, str(e))
        except (llm_answer.RateLimitError, llm_refine_choice.RateLimitError) as e:
            if attempt >= max_attempts:
                return ("error", item, str(e))
            time.sleep(min(e.retry_after + 1, 60))
        except (llm_answer.LLMError, llm_refine_choice.LLMError) as e:
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
    parser.add_argument("--model", default="deepseek-v4.1-flash")
    parser.add_argument("--base-url", default="https://api.tokenator.top/v1")
    parser.add_argument("--max-tokens", type=int, default=1500)
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--checkpoint-every", type=int, default=20)
    args = parser.parse_args()

    env = load_lead_pipeline_env()
    api_key = env["LLM_API_KEY"]
    timeout_sec = float(env.get("LLM_TIMEOUT_SEC", 180))
    max_attempts = int(env.get("LLM_MAX_ATTEMPTS", 4))

    data = json.loads(args.inp.read_text(encoding="utf-8"))
    targets = [d for d in data if not d.get("correct")]
    print(f"Целей на передёргивание (пустой correct): {len(targets)} из {len(data)}", file=sys.stderr)
    if not targets:
        return

    lock = threading.Lock()
    fatal_holder = {"error": None}
    since_checkpoint = 0
    done_count = 0
    stats = {"fixed": 0, "still_empty": 0, "errors": 0}

    def save():
        args.inp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(retry_one, item, args.base_url, api_key, args.model, args.max_tokens,
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
                    if item.get("correct"):
                        stats["fixed"] += 1
                    else:
                        stats["still_empty"] += 1
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

    print(f"\nГотово: исправлено={stats['fixed']}, всё ещё пусто={stats['still_empty']}, "
          f"ошибок={stats['errors']} -> {args.inp}", file=sys.stderr)


if __name__ == "__main__":
    main()
