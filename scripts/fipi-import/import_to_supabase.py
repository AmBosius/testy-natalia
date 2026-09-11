#!/usr/bin/env python3
"""
Импорт распарсенных и размеченных заданий ФИПИ в Supabase.

Разово: режет большие тематические подборки (test_title) на тесты по
CHUNK_SIZE заданий, создаёт tests/questions/answers через REST API,
логинясь под админом (тем же, что и в самой админке сайта).

Использование:
    ADMIN_EMAIL=... ADMIN_PASSWORD=... python import_to_supabase.py \
        data/final/rus_final_llm.json data/final/rus_grades_llm.json

Требует: pip install requests
"""

import json
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

SUPABASE_URL = "https://mypjlvxvcpsajaibjvwo.supabase.co"
ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im15cGpsdnh2Y3BzYWphaWJqdndvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODkxMTc1NTksImV4cCI6MjEwNDY5MzU1OX0."
    "ubtqCKZ3wyUm3k-Y2tQT-6bqDLKZV7MH22_AouDAmAk"
)

ALLOWED_TYPES = {"choice", "multi-choice", "sentence-number", "word", "digits"}
ALLOWED_SECTIONS = {"5", "6", "7", "8", "9", "10", "11", "oge", "ege"}
CHUNK_SIZE = 10
MAX_WORKERS = 6


def login(email, password):
    r = requests.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": ANON_KEY, "Content-Type": "application/json"},
        json={"email": email, "password": password},
        timeout=30,
    )
    if not r.ok:
        print(f"Ошибка входа ({r.status_code}): {r.text}")
        sys.exit(1)
    return r.json()["access_token"]


def auth_headers(token):
    return {
        "apikey": ANON_KEY,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def load_items(paths):
    items = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for d in data:
            if d.get("type") not in ALLOWED_TYPES:
                continue
            if d.get("section") not in ALLOWED_SECTIONS:
                continue
            if not (d.get("text") or "").strip():
                continue
            items.append(d)
    return items


def group_by_test_title(items):
    groups = {}
    order = []
    for it in items:
        key = it["test_title"]
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(it)
    return [(k, groups[k]) for k in order]


def chunk(lst, size):
    return [lst[i : i + size] for i in range(0, len(lst), size)]


def build_plan(items):
    """Возвращает список тестов вида {test: {...}, questions: [{...с _correct/_digit_set}]}."""
    plan = []
    for title, group_items in group_by_test_title(items):
        chunks = chunk(group_items, CHUNK_SIZE)
        multi = len(chunks) > 1
        for variant_idx, part in enumerate(chunks, start=1):
            first = part[0]
            test_title = title if not multi else f"{title} — вариант {variant_idx}"
            test_row = {
                "id": f"fipi-{uuid.uuid4().hex[:12]}",
                "title": test_title[:250],
                "section": first["section"],
                "topic": first.get("topic") or "Без темы",
                "level": first.get("level") if first.get("level") in (1, 2, 3) else 1,
            }
            questions = []
            for pos, q in enumerate(part, start=1):
                correct = q.get("correct") or []
                needs_review = bool(q.get("needs_review")) or not correct
                questions.append(
                    {
                        "position": pos,
                        "type": q["type"],
                        "text": q["text"],
                        "passage": q.get("passage") or None,
                        "options": q.get("options") or None,
                        "hint": q.get("hint") or None,
                        "published": not needs_review,
                        "_correct": correct or ["(нет ответа — заполните вручную)"],
                        "_digit_set": bool(q.get("digit_set")),
                    }
                )
            plan.append({"test": test_row, "questions": questions})
    return plan


def import_one_test(entry, token):
    test = entry["test"]
    questions = entry["questions"]
    h = auth_headers(token)

    r = requests.post(f"{SUPABASE_URL}/rest/v1/tests", headers=h, json=test, timeout=30)
    r.raise_for_status()

    q_payload = [
        {
            "test_id": test["id"],
            "position": q["position"],
            "type": q["type"],
            "text": q["text"],
            "passage": q["passage"],
            "options": q["options"],
            "hint": q["hint"],
            "published": q["published"],
        }
        for q in questions
    ]
    h_repr = dict(h, Prefer="return=representation")
    r = requests.post(f"{SUPABASE_URL}/rest/v1/questions", headers=h_repr, json=q_payload, timeout=30)
    r.raise_for_status()
    inserted = r.json()

    by_position = {row["position"]: row["id"] for row in inserted}
    a_payload = [
        {
            "question_id": by_position[q["position"]],
            "correct": q["_correct"],
            "digit_set": q["_digit_set"],
        }
        for q in questions
    ]
    r = requests.post(f"{SUPABASE_URL}/rest/v1/answers", headers=h, json=a_payload, timeout=30)
    r.raise_for_status()

    return test["id"], len(questions)


def main():
    email = os.environ.get("ADMIN_EMAIL")
    password = os.environ.get("ADMIN_PASSWORD")
    if not email or not password:
        print("Задайте переменные окружения ADMIN_EMAIL и ADMIN_PASSWORD.")
        sys.exit(1)

    paths = sys.argv[1:]
    if not paths:
        print("Использование: python import_to_supabase.py файл1.json [файл2.json ...]")
        sys.exit(1)

    print("Логинюсь...")
    token = login(email, password)

    print("Читаю и группирую задания...")
    items = load_items(paths)
    plan = build_plan(items)
    total_questions = sum(len(e["questions"]) for e in plan)
    print(f"Тестов к созданию: {len(plan)}, заданий: {total_questions}")

    done = 0
    errors = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(import_one_test, entry, token): entry for entry in plan}
        for future in as_completed(futures):
            entry = futures[future]
            try:
                test_id, n = future.result()
                done += 1
                if done % 20 == 0:
                    print(f"...{done}/{len(plan)} тестов")
            except Exception as e:
                errors.append((entry["test"]["title"], str(e)))

    print(f"Готово: {done}/{len(plan)} тестов загружено.")
    if errors:
        print(f"Ошибок: {len(errors)}")
        with open("import_errors.json", "w", encoding="utf-8") as f:
            json.dump(errors, f, ensure_ascii=False, indent=2)
        print("Подробности в import_errors.json")


if __name__ == "__main__":
    main()
