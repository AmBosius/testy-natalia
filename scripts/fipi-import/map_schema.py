#!/usr/bin/env python3
"""
Шаг 3: превращает "сырой" JSON (fetch_fipi.py) в массив заданий под схему
проекта testy-natalia (см. supabase/schema.sql — поля questions/answers,
плюс test_title/needs_review для последующей ручной сборки в тесты):

{
  "section": "oge"|"ege",
  "topic": "строка",
  "level": 1|2|3,
  "test_title": "строка",
  "type": "choice"|"sentence-number"|"word"|"digits",
  "text": "...", "passage": "..."|null,
  "options": [...]|null, "hint": null,
  "correct": [], "digit_set": true|false,
  "needs_review": true
}

Разметка типа задания и text/passage — эвристики по ключевым словам и
структуре HTML (регэкспы, см. classify_type/split_text_passage), а не
ручной построчный просмотр каждого задания моделью.

ВАЖНОЕ ОГРАНИЧЕНИЕ: открытый банк ФИПИ нигде не публикует правильные
ответы (проверено на ЕГЭ и ОГЭ — проверка ответа идёт на сервере,
клиенту возвращается только код "решено/неверно"). Поэтому здесь
"correct" всегда остаётся пустым, а "needs_review" — true. Реальные
ответы либо вписываются вручную, либо (для этого проекта) достаются
отдельным шагом llm_answer.py через LLM — см. README.md.

Часть заданий (эссе "Развёрнутый ответ", "Расстановка терминов" и т.п.)
не укладывается ни в один из 4 типов схемы — такие пропускаются, их
guid/short_id есть в raw JSON, ничего не теряется.

Использование:
    python map_schema.py --in data/raw/rus_ege_raw.json data/raw/rus_oge_raw.json \
        --out data/final/rus_final.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

EXAM_TITLES = {"ege": "ЕГЭ", "oge": "ОГЭ"}

DIGIT_RE = re.compile(r"цифр")
MATCH_CORRESPOND_RE = re.compile(r"соответств")
SENTENCE_NUM_RE = re.compile(
    r"найдите\b.{0,15}предложени|укажите номер.{0,15}предложени|"
    r"запишите номер.{0,15}предложени|среди предложени|"
    r"в каком из предложени"
)
WORD_HINT_RE = re.compile(r"слов")
PAREN_DIGIT_RE = re.compile(r"\(\d+\)")


def classify_type(record: dict) -> tuple[str | None, bool]:
    """Возвращает (type, digit_set) либо (None, False), если задание не
    укладывается ни в один из 4 типов схемы (эссе, расстановка терминов…)."""
    rik = record.get("raw_input_kind")
    text_l = f"{record.get('question_text') or ''} {record.get('hint') or ''}".lower()

    if rik in ("checkbox", "radio"):
        return "choice", False

    if rik == "select":
        # Установление соответствия (напр. задание 8 ЕГЭ, ошибки в
        # грамматике): ответ — последовательность цифр по числу букв
        # (А, Б, В...), порядок важен — это не набор, а сопоставление.
        return "digits", False

    if rik == "text":
        if DIGIT_RE.search(text_l):
            digit_set = not MATCH_CORRESPOND_RE.search(text_l)
            return "digits", digit_set
        if SENTENCE_NUM_RE.search(text_l):
            return "sentence-number", False
        # "Выпишите слово(-а)", "замените слово", "образуйте форму слова" и т.п.
        # — это и есть дефолт для короткого текстового ответа.
        return "word", False

    # rik in ("unknown",) — эссе (Развёрнутый ответ), расстановка терминов
    # и прочие форматы без чёткого маппинга в схему. Пропускаем.
    return None, False


def strip_kes_code(kes_text: str) -> str:
    return re.sub(r"^\d[\d.]*\s+", "", kes_text).strip()


def split_text_passage(record: dict, qtype: str) -> tuple[str, str | None]:
    """Разводит инструкцию (text) и прикреплённый текст/предложение (passage).

    1) Если задание входит в группу с общим текстом (см. fetch_fipi.py —
       passage_text из предшествующего безguid-ового qblock) — используем его.
    2) Иначе для digits/sentence-number пробуем найти абзац с маркерами
       "(1) (2) ..." — всё до него это инструкция, он сам и всё после — passage.
    3) Иначе для word с ровно 2 абзацами — второй абзац считаем источником
       (предложение, откуда выписывать слово), первый — инструкцией.
    4) Иначе не разделяем — всё в text, passage=None (не гадаем).
    """
    passage_text = record.get("passage_text")
    if passage_text:
        return record.get("question_text") or "", passage_text

    paragraphs = record.get("paragraphs") or []
    full_text = record.get("question_text") or ""

    if qtype in ("digits", "sentence-number") and len(paragraphs) >= 2:
        for i, p in enumerate(paragraphs):
            if PAREN_DIGIT_RE.search(p):
                if i == 0:
                    break  # инструкция и предложение слиты в одном абзаце
                return " ".join(paragraphs[:i]), " ".join(paragraphs[i:])

    if qtype == "word" and len(paragraphs) == 2:
        return paragraphs[0], paragraphs[1]

    return full_text, None


def guess_level(record: dict, qtype: str) -> int:
    """ФИПИ не публикует уровень сложности для русского языка (нет фильтра
    qlevel на сайте) — это грубая эвристика, а не авторитетная оценка.
    ОГЭ считаем базовым уровнем; для ЕГЭ ориентируемся на формат ответа:
    выбор/краткий ответ — средний, сопоставление — сложный."""
    if record.get("source_exam") == "oge":
        return 1
    if record.get("raw_input_kind") in ("select", "unknown"):
        return 3
    return 2


def build_test_title(record: dict) -> str:
    exam_title = EXAM_TITLES.get(record.get("source_exam"), record.get("source_exam", ""))
    kes_texts = record.get("kes_texts") or []
    if kes_texts:
        topic = strip_kes_code(kes_texts[0])
        if len(topic) > 70:
            topic = topic[:67].rstrip() + "…"
        return f"{exam_title}. Русский язык — {topic}"
    return f"{exam_title}. Русский язык"


def build_topic(record: dict) -> str:
    kes_texts = record.get("kes_texts") or []
    if not kes_texts:
        return "Без темы (КЭС не указан)"
    return " | ".join(kes_texts)


def map_record(record: dict) -> dict | None:
    qtype, digit_set = classify_type(record)
    if qtype is None:
        return None

    text, passage = split_text_passage(record, qtype)
    options = record.get("options") if qtype == "choice" else None

    return {
        "section": record.get("source_exam"),
        "topic": build_topic(record),
        "level": guess_level(record, qtype),
        "test_title": build_test_title(record),
        "type": qtype,
        "text": text,
        "passage": passage,
        "options": options,
        "hint": None,
        "correct": [],
        "digit_set": digit_set,
        "needs_review": True,
        # Технические поля не из схемы БД — для трассировки и шага 4 (LLM).
        # admin.js/import-скрипт может просто игнорировать ключи с "_".
        "_source_guid": record.get("guid"),
        "_source_short_id": record.get("short_id"),
        "_source_exam": record.get("source_exam"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="inputs", nargs="+", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    raw_records = []
    for path in args.inputs:
        raw_records.extend(json.loads(path.read_text(encoding="utf-8")))

    mapped = []
    skipped_by_kind = {}
    for r in raw_records:
        m = map_record(r)
        if m is None:
            label = r.get("answer_kind_label") or r.get("raw_input_kind") or "?"
            skipped_by_kind[label] = skipped_by_kind.get(label, 0) + 1
            continue
        mapped.append(m)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(mapped, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Вход: {len(raw_records)} записей", file=sys.stderr)
    print(f"Размечено: {len(mapped)} -> {args.out}", file=sys.stderr)
    if skipped_by_kind:
        print("Пропущено (не укладывается в 4 типа схемы):", file=sys.stderr)
        for label, count in sorted(skipped_by_kind.items(), key=lambda x: -x[1]):
            print(f"  {label}: {count}", file=sys.stderr)


if __name__ == "__main__":
    main()
