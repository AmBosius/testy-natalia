#!/usr/bin/env python3
"""
Шаг 2: скачивает "сырые" задания по русскому языку из открытого банка ФИПИ
(ege.fipi.ru / oge.fipi.ru) и складывает их в промежуточный JSON — как есть,
без разметки под нашу схему (это делает map_schema.py).

Источник данных, найденный руками через Network-вкладку браузера:

    GET https://{домен}.fipi.ru/bank/questions.php?proj=<GUID>&page=<N>&pagesize=100

Возвращает HTML-фрагмент с пачкой заданий (максимум 100 за раз, сервер сам
обрезает бОльший pagesize). page начинается с 0. Пустая пачка (0 заданий) —
конец списка. Источники "Русский язык":
  - ЕГЭ: ege.fipi.ru, proj=AF0ED3F2557F8FFC4C06F80B6803FD26
  - ОГЭ: oge.fipi.ru, proj=2F5EE3B12FE2A0EA40B06BF61A015416
  - Банк оценочных средств 1-11 классов (fipi.ru/otkrytyy-bank-otsenochnykh-sredstv-po-russkomu-yazyku):
    oge.fipi.ru (тот же движок, другой proj!), proj=BD98FF424631BFE24D6010A4B1266CA8.
    ВАЖНО: у этого банка другие поля в инфопанели ("Класс"/"Раздел" вместо
    "КЭС"/"Тип ответа") и ~99% заданий вообще без input (письмо на бумаге,
    устная речь — оценивает учитель, не сайт). См. README.md.

Правильные ответы сайт НИГДЕ не отдаёт (ни в HTML, ни в AJAX) — проверка
ответа идёт на сервере (solve.php), клиенту возвращается только код
0/1/2/3 (решено/неверно/верно). Это архитектурное ограничение ФИПИ, не
баг скрапера: поле с ответом в промежуточном JSON просто отсутствует.

Использование:
    python fetch_fipi.py --exam ege --out data/raw/rus_ege_raw.json
    python fetch_fipi.py --exam oge --out data/raw/rus_oge_raw.json
    python fetch_fipi.py --exam both --out-dir data/raw
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SOURCES = {
    "ege": {"domain": "ege.fipi.ru", "proj": "AF0ED3F2557F8FFC4C06F80B6803FD26"},
    "oge": {"domain": "oge.fipi.ru", "proj": "2F5EE3B12FE2A0EA40B06BF61A015416"},
    "grades": {"domain": "oge.fipi.ru", "proj": "BD98FF424631BFE24D6010A4B1266CA8"},
}

PAGE_SIZE = 100
REQUEST_DELAY_SEC = 0.6  # вежливая пауза между запросами, чтобы не долбить сайт
MAX_PAGES = 200  # предохранитель от бесконечного цикла

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "FipiOpenBankScraper/1.0 (educational data collection)"
    ),
}


def fetch_page(session: requests.Session, domain: str, proj: str, page: int) -> str:
    url = f"https://{domain}/bank/questions.php"
    params = {"proj": proj, "page": page, "pagesize": PAGE_SIZE}
    resp = session.get(url, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = "windows-1251"
    return resp.text


def parse_info_panel(info_div) -> dict:
    """Достаёт пары параметр->значение из блока СВОЙСТВА ЗАДАНИЯ (КЭС, Тип ответа и т.п.)."""
    params = {}
    if info_div is None:
        return {"params": params, "short_id_label": None}
    for row in info_div.select("table tr"):
        name_cell = row.select_one("td.param-name")
        if not name_cell:
            continue
        cells = row.find_all("td")
        value_cell = cells[1] if len(cells) > 1 else None
        key = name_cell.get_text(strip=True).rstrip(":")
        if value_cell is None:
            params[key] = ""
            continue
        # КЭС может содержать несколько кодов классификатора — каждый в своём <div>.
        sub_divs = value_cell.find_all("div", recursive=False)
        if len(sub_divs) > 1:
            params[key] = [d.get_text(" ", strip=True) for d in sub_divs]
        else:
            params[key] = value_cell.get_text(" ", strip=True)

    id_text = info_div.select_one(".id-text")
    short_id = None
    if id_text:
        span = id_text.select_one("span")
        short_id = span.get_text(strip=True) if span else id_text.get_text(strip=True)

    return {"params": params, "short_id_label": short_id}


def parse_qblock(qblock) -> dict:
    hint_div = qblock.select_one("#hint")
    hint = hint_div.get_text(" ", strip=True) if hint_div else None

    guid_input = qblock.select_one('input[name="guid"]')
    guid = guid_input.get("value") if guid_input else None

    # Тело вопроса: первая жёлтая ячейка таблицы задания (bgcolor #FAFBCA / class cell_0).
    body_cell = qblock.select_one("td.cell_0")
    question_html = str(body_cell) if body_cell else None
    question_text = body_cell.get_text(" ", strip=True) if body_cell else None

    # Топ-уровневые <p> внутри тела — часто это [инструкция, размеченное
    # предложение/текст]. map_schema.py использует это, чтобы аккуратно
    # развести text/passage вместо одной слипшейся строки.
    paragraphs = []
    if body_cell:
        for p in body_cell.find_all("p", recursive=False):
            t = p.get_text(" ", strip=True)
            if t:
                paragraphs.append(t)
        if not paragraphs:
            # Иногда абзацы лежат не прямо в td, а во вложенной таблице/div —
            # просто нечего делить, остаётся один общий блок.
            paragraphs = [question_text] if question_text else []

    text_input = qblock.select_one('input[type="text"][name="answer"]')
    checkboxes = qblock.select('input[type="checkbox"]')
    radios = qblock.select('input[type="radio"]')
    selects = qblock.select("select")

    options = None
    if checkboxes or radios:
        options = []
        distractor_rows = qblock.select("table.distractors-table tr")
        for row in distractor_rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            # Обычно 3 ячейки (чекбокс, "N)", текст), но встречается и
            # 2-ячеечная вёрстка (чекбокс, текст) без отдельного номера —
            # текст варианта в любом случае в последней ячейке строки.
            option_text = cells[-1].get_text(" ", strip=True)
            options.append(option_text)

    select_count = None
    if text_input is not None:
        raw_input_kind = "text"
    elif checkboxes:
        raw_input_kind = "checkbox"
    elif radios:
        raw_input_kind = "radio"
    elif selects:
        # Установление соответствия (напр. задание 8 ЕГЭ): N выпадающих
        # списков — по одному на букву А), Б), В"... — с цифрами вариантов.
        raw_input_kind = "select"
        select_count = len(selects)
    else:
        raw_input_kind = "unknown"

    return {
        "guid": guid,
        "hint": hint,
        "question_html": question_html,
        "question_text": question_text,
        "paragraphs": paragraphs,
        "options": options,
        "raw_input_kind": raw_input_kind,
        "select_count": select_count,
    }


def parse_questions_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    records = []
    # Некоторые qblock — не задания, а общий текст-отрывок для группы вопросов
    # (напр. задания 22-26 ЕГЭ): у них нет ни id, ни guid/формы, только текст.
    # Идут в порядке документа перед вопросами, которые к ним относятся —
    # копим последний такой текст и прикрепляем как passage к обычным вопросам,
    # пока не встретится следующий отрывок (или конец страницы).
    current_passage = None

    for qblock in soup.select("div.qblock"):
        record = parse_qblock(qblock)

        if not record["guid"]:
            current_passage = record["question_text"]
            continue

        short_id = qblock.get("id", "")[1:]  # 'q4D1A4B' -> '4D1A4B'
        info_div = soup.select_one(f"#i{short_id}")
        info = parse_info_panel(info_div)
        record["short_id"] = short_id
        record["passage_text"] = current_passage

        kes_raw = info["params"].get("КЭС")
        kes_list = kes_raw if isinstance(kes_raw, list) else ([kes_raw] if kes_raw else [])
        record["kes_texts"] = kes_list
        record["kes_codes"] = []
        for entry in kes_list:
            parts = entry.split(" ", 1)
            if parts and parts[0].replace(".", "").isdigit():
                record["kes_codes"].append(parts[0])

        answer_kind = info["params"].get("Тип ответа")
        record["answer_kind_label"] = answer_kind if isinstance(answer_kind, str) else None

        # Банк 1-11 классов не даёт КЭС/Тип ответа — вместо этого "Класс"
        # ("5 класс") и "Раздел" (Чтение/Письмо/Слушание/Говорение/...).
        grade_raw = info["params"].get("Класс")
        record["grade_label"] = grade_raw if isinstance(grade_raw, str) else None
        section_raw = info["params"].get("Раздел")
        record["section_label"] = section_raw if isinstance(section_raw, str) else None

        record["extra_params"] = {
            k: v for k, v in info["params"].items()
            if k not in ("КЭС", "Тип ответа", "Класс", "Раздел")
        }

        records.append(record)
    return records


def scrape_exam(exam: str, out_path: Path, limit_pages: int | None = None) -> None:
    source = SOURCES[exam]
    domain, proj = source["domain"], source["proj"]
    session = requests.Session()
    all_records: list[dict] = []
    seen_guids: set[str] = set()

    print(f"[{exam}] старт скрапинга (domain={domain}, proj={proj})", file=sys.stderr)

    max_pages = limit_pages if limit_pages is not None else MAX_PAGES
    for page in range(max_pages):
        html = fetch_page(session, domain, proj, page)
        records = parse_questions_page(html)
        if not records:
            print(f"[{exam}] страница {page}: пусто, останавливаюсь", file=sys.stderr)
            break

        new_count = 0
        for r in records:
            if r["guid"] and r["guid"] in seen_guids:
                continue
            if r["guid"]:
                seen_guids.add(r["guid"])
            r["source_exam"] = exam
            r["source_page"] = page
            all_records.append(r)
            new_count += 1

        print(
            f"[{exam}] страница {page}: {len(records)} заданий ({new_count} новых, всего {len(all_records)})",
            file=sys.stderr,
        )

        if new_count == 0:
            # За пределами реального диапазона страниц ФИПИ отдаёт не пустой
            # список, а повторяет последнюю валидную страницу (проверено:
            # page=22..50 при 21 реальной странице возвращают один и тот же
            # байт-в-байт HTML). Раз новых guid нет — мы зациклились, стоп.
            print(f"[{exam}] страница {page}: без новых заданий (повтор), останавливаюсь", file=sys.stderr)
            break

        time.sleep(REQUEST_DELAY_SEC)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(all_records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[{exam}] готово: {len(all_records)} заданий -> {out_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exam", choices=["ege", "oge", "grades", "both"], default="both")
    parser.add_argument("--out", type=Path, help="путь к выходному файлу (для одного exam)")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).parent / "data" / "raw",
        help="директория для выходных файлов (при --exam both)",
    )
    parser.add_argument(
        "--limit-pages",
        type=int,
        default=None,
        help="ограничить число страниц (для быстрого тестового прогона)",
    )
    args = parser.parse_args()

    exams = ["ege", "oge"] if args.exam == "both" else [args.exam]
    for exam in exams:
        out_path = args.out if (args.out and len(exams) == 1) else args.out_dir / f"rus_{exam}_raw.json"
        scrape_exam(exam, out_path, limit_pages=args.limit_pages)


if __name__ == "__main__":
    main()
