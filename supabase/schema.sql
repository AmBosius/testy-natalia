-- ============================================================
-- Схема базы для тестов по русскому языку.
-- Выполнить целиком в Supabase SQL Editor одним запуском.
-- ============================================================

-- 1. Таблицы -------------------------------------------------

create table if not exists sections (
  id text primary key,
  title text not null,
  sort_order int not null
);

create table if not exists tests (
  id text primary key,
  title text not null,
  section text not null references sections(id),
  topic text not null,
  level int not null default 1,
  created_at timestamptz not null default now()
);

create table if not exists questions (
  id bigint generated always as identity primary key,
  test_id text not null references tests(id) on delete cascade,
  position int not null,
  type text not null check (type in ('choice', 'sentence-number', 'word', 'digits')),
  text text not null,
  passage text,
  options jsonb,
  hint text
);

-- Правильные ответы лежат отдельно от questions и никогда не отдаются
-- анонимному пользователю напрямую — только через функцию check_test ниже.
create table if not exists answers (
  question_id bigint primary key references questions(id) on delete cascade,
  correct jsonb not null,
  digit_set boolean not null default false
);

-- 2. Row Level Security ---------------------------------------

alter table sections enable row level security;
alter table tests enable row level security;
alter table questions enable row level security;
alter table answers enable row level security;

-- Публичное чтение: разделы, тесты, вопросы — видно всем (в т.ч. анонимам).
create policy "public read sections" on sections for select using (true);
create policy "public read tests" on tests for select using (true);
create policy "public read questions" on questions for select using (true);
-- На answers публичной select-политики намеренно нет — анонимный
-- пользователь не может прочитать эту таблицу вообще никак.

-- Запись: только авторизованный админ (у Натальи будет единственный
-- логин через Supabase Auth). Действует на все 4 таблицы.
create policy "admin write sections" on sections for all
  using (auth.role() = 'authenticated') with check (auth.role() = 'authenticated');
create policy "admin write tests" on tests for all
  using (auth.role() = 'authenticated') with check (auth.role() = 'authenticated');
create policy "admin write questions" on questions for all
  using (auth.role() = 'authenticated') with check (auth.role() = 'authenticated');
create policy "admin write answers" on answers for all
  using (auth.role() = 'authenticated') with check (auth.role() = 'authenticated');

-- 3. Проверка ответов на сервере --------------------------------
-- Логика 1-в-1 повторяет js/checker.js (normalize / normalizeDigits),
-- только выполняется в базе, чтобы answers никогда не покидали сервер
-- до момента нажатия «Проверить».

create or replace function normalize_text(v text) returns text
language sql immutable as $$
  select lower(regexp_replace(regexp_replace(replace(coalesce(v, ''), 'ё', 'е'), '\s+', '', 'g'), '[.,;:!?]', '', 'g'));
$$;

create or replace function normalize_digits(v text) returns text
language sql immutable as $$
  select coalesce(string_agg(c, '' order by c), '')
  from regexp_split_to_table(regexp_replace(coalesce(v, ''), '\D', '', 'g'), '') c
  where c <> '';
$$;

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
      if jsonb_typeof(given) = 'number' then
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

-- 4. Данные: разделы + три демо-теста, перенесённые из data/*.json ------

insert into sections (id, title, sort_order) values
  ('5', '5 класс', 1),
  ('6', '6 класс', 2),
  ('7', '7 класс', 3),
  ('8', '8 класс', 4),
  ('9', '9 класс', 5),
  ('10', '10 класс', 6),
  ('11', '11 класс', 7),
  ('oge', 'Подготовка к ОГЭ', 8),
  ('ege', 'Подготовка к ЕГЭ', 9)
on conflict (id) do nothing;

insert into tests (id, title, section, topic, level) values
  ('test-001', 'Морфология. Имя существительное', '5', 'Морфология', 1),
  ('test-002', 'Синтаксис. Однородные члены предложения', 'oge', 'Синтаксис и пунктуация', 2),
  ('test-003', 'Н и НН в причастиях и прилагательных', 'ege', 'Орфография', 2)
on conflict (id) do nothing;

-- test-001 --------------------------------------------------

insert into questions (test_id, position, type, text, options) values
  ('test-001', 1, 'choice', 'В каком ряду все существительные относятся к первому склонению?',
    '["земля, дядя, аллея", "конь, поле, стол", "мышь, ночь, рожь", "время, знамя, пламя", "окно, село, письмо"]'),
  ('test-001', 2, 'choice', 'Укажите существительное среднего рода.',
    '["тополь", "мозоль", "какао", "картофель", "шампунь"]'),
  ('test-001', 3, 'choice', 'В каком слове окончание -е?',
    '["о деревн...", "в тетрад...", "на площад...", "к матер...", "в галере..."]'),
  ('test-001', 9, 'choice', 'Укажите вариант, в котором существительное стоит в дательном падеже.',
    '["подошёл к дому", "вижу дом", "около дома", "живу в доме", "любуюсь домом"]');

insert into questions (test_id, position, type, text, passage) values
  ('test-001', 4, 'sentence-number', 'Найдите предложение, в котором есть существительное в винительном падеже. Запишите его номер.',
    '(1)За окном тихо падал снег. (2)Мальчик открыл толстую книгу. (3)Над лесом поднималось солнце.'),
  ('test-001', 5, 'sentence-number', 'Найдите предложение, в котором есть несклоняемое существительное. Запишите его номер.',
    '(1)Мы долго гуляли по набережной. (2)На столе стояла чашка горячего кофе. (3)Дети вернулись домой поздно вечером. (4)Ветер срывал последние листья.'),
  ('test-001', 10, 'sentence-number', 'Найдите предложение, в котором существительное является сказуемым. Запишите его номер.',
    '(1)Берёза — символ России. (2)Берёза растёт у самого крыльца. (3)Я посадил берёзу прошлой весной.');

insert into questions (test_id, position, type, text, passage, hint) values
  ('test-001', 6, 'word', 'Выпишите из предложения существительное третьего склонения.',
    'Ночь опустилась на притихший город, и в окнах загорелись первые огни.', 'Пишите строчными буквами, без пробелов'),
  ('test-001', 7, 'word', 'Выпишите из предложения существительное в творительном падеже.',
    'Дорога шла лесом и постепенно поднималась в гору.', 'Пишите строчными буквами, без пробелов'),
  ('test-001', 8, 'word', 'Выпишите из предложения существительное, которое употребляется только во множественном числе.',
    'Мама убрала ножницы в верхний ящик стола.', 'Пишите строчными буквами, без пробелов');

insert into answers (question_id, correct)
select id, val from (values
  (1, '[0]'::jsonb), (2, '[2]'::jsonb), (3, '[0]'::jsonb), (9, '[0]'::jsonb)
) as t(pos, val)
join questions q on q.test_id = 'test-001' and q.position = t.pos;

insert into answers (question_id, correct)
select id, val from (values
  (4, '["2"]'::jsonb), (5, '["2"]'::jsonb), (10, '["1"]'::jsonb)
) as t(pos, val)
join questions q on q.test_id = 'test-001' and q.position = t.pos;

insert into answers (question_id, correct)
select id, val from (values
  (6, '["ночь"]'::jsonb), (7, '["лесом"]'::jsonb), (8, '["ножницы"]'::jsonb)
) as t(pos, val)
join questions q on q.test_id = 'test-001' and q.position = t.pos;

-- test-002 --------------------------------------------------

insert into questions (test_id, position, type, text, passage) values
  ('test-002', 1, 'sentence-number', 'Найдите предложение с однородными сказуемыми. Запишите его номер.',
    '(1)Ветер стих, и над рекой повис туман. (2)Лодка качнулась и медленно отошла от берега. (3)На противоположном берегу горел костёр.'),
  ('test-002', 2, 'sentence-number', 'Найдите предложение с однородными определениями. Запишите его номер.',
    '(1)У калитки нас встретил старый лохматый пёс. (2)По двору бегали куры. (3)За домом начинался сад.');

insert into questions (test_id, position, type, text, options) values
  ('test-002', 3, 'choice', 'В каком предложении при однородных членах нужно поставить двоеточие?',
    '["В корзине лежали разные ягоды малина, черника, земляника.", "Малина и черника росли у самой тропинки.", "Мы собирали ягоды и грибы.", "Ягоды были крупные и сладкие.", "Он выбрал малину, а не чернику."]');

insert into questions (test_id, position, type, text, passage, hint) values
  ('test-002', 4, 'word', 'Выпишите любое из однородных сказуемых предложения.',
    'Дождь то стихал, то снова барабанил по крыше.', 'Пишите строчными буквами, без пробелов. Достаточно одного слова'),
  ('test-002', 5, 'word', 'Выпишите обобщающее слово при однородных членах предложения.',
    'Всюду: на подоконниках, на полках, на письменном столе — лежали книги.', 'Пишите строчными буквами, без пробелов');

insert into answers (question_id, correct)
select id, val from (values
  (1, '["2"]'::jsonb), (2, '["1"]'::jsonb)
) as t(pos, val)
join questions q on q.test_id = 'test-002' and q.position = t.pos;

insert into answers (question_id, correct)
select id, '[0]'::jsonb from questions where test_id = 'test-002' and position = 3;

insert into answers (question_id, correct)
select id, val from (values
  (4, '["стихал", "барабанил"]'::jsonb), (5, '["всюду"]'::jsonb)
) as t(pos, val)
join questions q on q.test_id = 'test-002' and q.position = t.pos;

-- test-003 --------------------------------------------------

insert into questions (test_id, position, type, text, passage, hint) values
  ('test-003', 1, 'digits', 'Укажите цифру(-ы), на месте которой(-ых) пишется НН.',
    'На подоконнике лежала вяза(1)ая шапка, связа(2)ая бабушкой прошлой зимой, а рядом — купле(3)ый вчера шарф.',
    'Может быть несколько цифр, порядок не важен — например: 12'),
  ('test-003', 2, 'digits', 'Укажите цифру(-ы), на месте которой(-ых) пишется НН.',
    'Игрушка была брошe(1)а на пол, а разброса(2)ые повсюду детали мешали пройти; давно небеле(3)ый потолок требовал ремонта.',
    'Может быть несколько цифр, порядок не важен');

insert into questions (test_id, position, type, text, options) values
  ('test-003', 3, 'choice', 'Укажите пример, в котором на месте пропуска пишется НН.',
    '["ветре..ый день", "исти..ая история", "кожа..ый ремень", "серебря..ый кубок", "масля..ая краска"]');

insert into answers (question_id, correct, digit_set)
select id, val, true from (values
  (1, '["23"]'::jsonb), (2, '["2"]'::jsonb)
) as t(pos, val)
join questions q on q.test_id = 'test-003' and q.position = t.pos;

insert into answers (question_id, correct)
select id, '[1]'::jsonb from questions where test_id = 'test-003' and position = 3;
