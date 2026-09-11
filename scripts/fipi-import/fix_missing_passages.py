#!/usr/bin/env python3
"""
Чинит конкретный баг: у блоков-отрывков без guid (общий текст для группы
вопросов) не было <table>/td.cell_0 — старый парсер молча терял их текст,
и подключённые к ним вопросы (напр. классическое задание 2 ЕГЭ "подберите
союз... в первом предложении ТЕКСТА") оставались без passage, из-за чего
ни одна модель не могла на них ответить (см. обсуждение в сессии — Sonnet
и DeepSeek одинаково спасовали именно на этих заданиях).

fetch_fipi.py уже пофикшен. Этот скрипт:
1. Смотрит свежеперескрейпленный raw (data/raw_v2/...) — там passage_text
   у некоторых записей теперь появился, где раньше был null.
2. Для каждой записи в уже готовом финальном файле (rus_final_llm.json /
   rus_grades_llm.json) ищет её по _source_guid в свежем raw.
3. Если раньше passage был null/отсутствовал, а теперь появился —
   проставляет его и СБРАСЫВАЕТ correct/needs_review/_llm_model, чтобы её
   переспросили заново (с текстом, который теперь реально есть).
   Остальные записи (у которых passage не изменился) не трогает вообще —
   вся уже проделанная LLM-разметка сохраняется.

Использование:
    python fix_missing_passages.py --final data/final/rus_final_llm.json \
        --raw-v2 data/raw_v2/rus_ege_raw.json data/raw_v2/rus_oge_raw.json
    python fix_missing_passages.py --final data/final/rus_grades_llm.json \
        --raw-v2 data/raw_v2/rus_grades_raw.json
"""
import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final", required=True, type=Path)
    parser.add_argument("--raw-v2", nargs="+", required=True, type=Path)
    args = parser.parse_args()

    raw_by_guid = {}
    for path in args.raw_v2:
        for rec in json.loads(path.read_text(encoding="utf-8")):
            if rec.get("guid"):
                raw_by_guid[rec["guid"]] = rec

    final = json.loads(args.final.read_text(encoding="utf-8"))
    fixed = 0
    for item in final:
        guid = item.get("_source_guid")
        if not guid or item.get("passage"):
            continue  # уже был passage — не трогаем
        raw = raw_by_guid.get(guid)
        if not raw:
            continue
        new_passage = raw.get("passage_text")
        if not new_passage:
            continue  # и в свежем скрейпе пусто — реально нет отрывка

        item["passage"] = new_passage
        item["correct"] = []
        item["needs_review"] = True
        item.pop("_llm_model", None)
        item.pop("_llm_confidence", None)
        item.pop("_llm_refined", None)
        item.pop("_retried_empty", None)
        item["_passage_recovered"] = True
        fixed += 1

    args.final.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{args.final}: восстановлен passage у {fixed} заданий (сброшены на переразметку)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
