#!/usr/bin/env python3
"""
Все source-задания type="choice" в нашем пайплайне изначально были
чекбоксами на сайте ФИПИ (ни одного radio-инпута не встретилось ни в
ЕГЭ/ОГЭ, ни в банке классов) — а часть классических заданий такого рода
(напр. задание 9 ЕГЭ: "укажите варианты ответов, в которых...") по
формату ФИПИ имеет РОВНО 2 правильных варианта из 5, не один.

Наша схема/промпт физически хранит в "correct" только ОДИН индекс —
поэтому для checkbox-заданий мы не можем отличить "тут правда один
ответ" от "тут правда два, а мы поймали только один". Пока это не
починено на уровне схемы/промпта, самое честное — считать все
type="choice" требующими ручной проверки.

Применяет needs_review=true ко всем type="choice" записям в файле(ах).
Использование:
    python patch_choice_review.py data/final/rus_final_llm.json data/final/rus_grades_llm.json
"""
import json
import sys
from pathlib import Path


def patch(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    total_choice = sum(1 for d in data if d.get("type") == "choice")
    changed = 0
    for d in data:
        if d.get("type") == "choice" and not d.get("needs_review"):
            d["needs_review"] = True
            changed += 1
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{path}: patched {changed} of {total_choice} choice items", file=sys.stderr)


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        patch(Path(arg))
