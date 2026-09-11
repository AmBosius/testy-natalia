-- ============================================================
-- Миграция: флаг «опубликовано» у заданий.
-- Нужен для массового импорта из ФИПИ — задания с needs_review
-- попадают в базу для проверки в админке, но не показываются
-- ученикам на сайте, пока не опубликованы.
-- Выполнить один раз в SQL Editor после предыдущих миграций.
-- ============================================================

alter table questions add column if not exists published boolean not null default true;

-- Публичное чтение вопросов теперь только опубликованных.
-- Админ (authenticated) по-прежнему видит всё через отдельную policy
-- "admin write questions" (for all, без условия published).
drop policy if exists "public read questions" on questions;
create policy "public read questions" on questions for select using (published = true);
