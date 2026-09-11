-- ============================================================
-- Миграция: тип задания «выбор нескольких вариантов» (multi-choice).
-- Выполнить один раз в SQL Editor после исходной schema.sql.
-- ============================================================

-- 1. Разрешить новый тип в questions.type -------------------

alter table questions drop constraint if exists questions_type_check;
alter table questions add constraint questions_type_check
  check (type in ('choice', 'multi-choice', 'sentence-number', 'word', 'digits'));

-- 2. Обновить check_test: добавить ветку для массива --------
-- Для multi-choice ученик присылает массив выбранных индексов,
-- верно только если это ТОЧНО то же множество, что в answers.correct
-- (порядок неважен, как с цифрами — но по индексам, а не по цифрам строки).

create or replace function check_test(p_test_id text, p_answers jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  total int := 0;
  correct_count int := 0;
  by_question jsonb := '{}'::jsonb;
  q record;
  given jsonb;
  given_text text;
  is_ok boolean;
  given_set int[];
  correct_set int[];
begin
  for q in
    select qs.id, qs.type, a.correct, a.digit_set
    from questions qs
    join answers a on a.question_id = qs.id
    where qs.test_id = p_test_id
    order by qs.position
  loop
    total := total + 1;
    given := p_answers -> q.id::text;
    is_ok := false;

    if given is not null and given <> 'null'::jsonb then
      if jsonb_typeof(given) = 'array' then
        -- multi-choice: сравниваем как множества индексов
        select array_agg((elem)::text::int order by (elem)::text::int)
          into given_set
          from jsonb_array_elements(given) elem;
        select array_agg((elem)::text::int order by (elem)::text::int)
          into correct_set
          from jsonb_array_elements(q.correct) elem
          where jsonb_typeof(elem) = 'number';
        is_ok := coalesce(given_set = correct_set, false);
      elsif jsonb_typeof(given) = 'number' then
        select coalesce(bool_or((elem)::text::int = (given)::text::int), false) into is_ok
        from jsonb_array_elements(q.correct) elem
        where jsonb_typeof(elem) = 'number';
      else
        given_text := given #>> '{}';
        if q.digit_set then
          select coalesce(bool_or(normalize_digits(elem #>> '{}') = normalize_digits(given_text)), false) into is_ok
          from jsonb_array_elements(q.correct) elem
          where jsonb_typeof(elem) = 'string';
        else
          select coalesce(bool_or(normalize_text(elem #>> '{}') = normalize_text(given_text)), false) into is_ok
          from jsonb_array_elements(q.correct) elem
          where jsonb_typeof(elem) = 'string';
        end if;
      end if;
    end if;

    if is_ok then correct_count := correct_count + 1; end if;

    by_question := by_question || jsonb_build_object(
      q.id::text,
      jsonb_build_object('correct', is_ok, 'accepted', q.correct)
    );
  end loop;

  return jsonb_build_object('total', total, 'correct', correct_count, 'byQuestion', by_question);
end;
$$;

grant execute on function check_test(text, jsonb) to anon, authenticated;
