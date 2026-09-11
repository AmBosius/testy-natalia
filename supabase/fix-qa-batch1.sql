-- ============================================================
-- QA-фикс 2026-09-11/12: массовые проблемы в данных из ФИПИ-импорта
-- ============================================================

-- 1) Join-фикс: 52 word-заданий, где несколько РАЗНЫХ пропусков
-- были сохранены как отдельные АЛЬТЕРНАТИВЫ вместо одной строки через
-- запятую - из-за этого ответ ученика никогда не засчитывался.

update answers set correct = '["агентство, дилетантский, здравствовать, интриганский, предчувствие, ровесник, сверстник, сумасшедший, участвовать, участливый, чествовать, шествовать, явственный"]'::jsonb where question_id = 3616; -- fipi-2c91420feaa0
update answers set correct = '["жилых, жилищной, старинных, старые, гарантийную, гарантированный, праздничный, праздный, злостным, злостный, наследие, наследство"]'::jsonb where question_id = 4011; -- fipi-35e294f00017
update answers set correct = '["вежливо, невежливо, корректно, учтиво, галантно, заносчиво, высокомерно, грубо, спесиво, манерно, церемонно"]'::jsonb where question_id = 5442; -- fipi-a13f3cb858ce
update answers set correct = '["ночевать, проповедовать, докладывать, рассматривать, растаять, видел, заметил, примерил, затеял, маскировать"]'::jsonb where question_id = 5351; -- fipi-bb82078d77ae
update answers set correct = '["христиани́н, киломе́тр, алфави́т, щаве́ль, каучу́к, инструме́нт, ту́фля, опто́вый, позвони́т, красиве́йший"]'::jsonb where question_id = 5700; -- fipi-eec42f029823
update answers set correct = '["моя фамилия, яблочным повидлом, проворная мышь, столичное метро, дорогой тюль, застарелая мозоль"]'::jsonb where question_id = 3176; -- fipi-b947b186ad06
update answers set correct = '["комическое, грациозно, неуклюже, врага, незаметно, невольно"]'::jsonb where question_id = 5068; -- fipi-b58d09163376
update answers set correct = '["пожелтевшей, раскрашенных, опавшая, пролетающие, наполненном, расцвеченному"]'::jsonb where question_id = 5431; -- fipi-05261e92ac55
update answers set correct = '["грохочущий, лающий, славящийся, тающий, дышащий, бреющийся"]'::jsonb where question_id = 4229; -- fipi-0645267ba00f
update answers set correct = '["вправо, вниз, неожиданно, густо, вокруг, неохотно"]'::jsonb where question_id = 5029; -- fipi-af7c7ce5dac9
update answers set correct = '["лихо, палатах, троне, венце, думой"]'::jsonb where question_id = 3976; -- fipi-05cab19e8ca4
update answers set correct = '["меня, себе, нему, его, вас"]'::jsonb where question_id = 3961; -- fipi-e41940764c83
update answers set correct = '["освоить, доверительная, главную, командировочное, двойную"]'::jsonb where question_id = 4003; -- fipi-91cdbc4105ae
update answers set correct = '["целлюлоза, кавалерист, артиллерия, коллаж, аллегория"]'::jsonb where question_id = 4127; -- fipi-9d660f0d63c4
update answers set correct = '["безвкусный, безрадостный, бескрайний, бесцветный, бесшумный"]'::jsonb where question_id = 5357; -- fipi-bb82078d77ae
update answers set correct = '["вниз, туда, круто, вправо, вдруг"]'::jsonb where question_id = 5071; -- fipi-b58d09163376
update answers set correct = '["гречиха, пашня, скат, печать, жар"]'::jsonb where question_id = 5689; -- fipi-86236d149136
update answers set correct = '["Пушкин, Гоголь, Толстой, Бунин"]'::jsonb where question_id = 3876; -- fipi-2986de64cab3
update answers set correct = '["убедить, очучиться, обезлюдить, чудить"]'::jsonb where question_id = 3900; -- fipi-65260b126def
update answers set correct = '["в Наполеоны, шапка Мономаха, во время чумы, разбитого корыта"]'::jsonb where question_id = 3948; -- fipi-b1785d18310b
update answers set correct = '["радоваться окончанию, поздравить с окончанием, надеяться на возвращение, опираться на факты"]'::jsonb where question_id = 4318; -- fipi-0d8fa24cadaf
update answers set correct = '["кружатся, вихрятся, носятся, мчатся"]'::jsonb where question_id = 5320; -- fipi-36b3b148fd94
update answers set correct = '["совпадает, нет, помню, можешь"]'::jsonb where question_id = 5521; -- fipi-ca4381cc293c
update answers set correct = '["господский, школьный, заводской, детский"]'::jsonb where question_id = 5535; -- fipi-80ac1896403b
update answers set correct = '["баллада, коллекция, иллюзия, галлерея"]'::jsonb where question_id = 4043; -- fipi-9c207f52677f
update answers set correct = '["кружатся, вихрятся, носятся, мчатся"]'::jsonb where question_id = 4106; -- fipi-7304bd566302
update answers set correct = '["синонимы, антонимы, омонимы, фразеологизм"]'::jsonb where question_id = 5446; -- fipi-3025730eba2a
update answers set correct = '["поэту, древнерусской литературы, воинам-освободителям, Сталинградской битвы"]'::jsonb where question_id = 5307; -- fipi-8b8f4d7a6996
update answers set correct = '["масштаб, почтамт, рыцарь, рюкзак"]'::jsonb where question_id = 5687; -- fipi-15016b4ca268
update answers set correct = '["о спящей кошке, в тяжелейшем положении, о замужней женщине, на последней странице"]'::jsonb where question_id = 4182; -- fipi-9cc6bae2f32b
update answers set correct = '["заслышав, свесившись, упёршись, насмотревшись"]'::jsonb where question_id = 5458; -- fipi-6b8f48772eb8
update answers set correct = '["бич, скаут, блокбастер, коктейль"]'::jsonb where question_id = 5694; -- fipi-86236d149136
update answers set correct = '["бакенбарды, аншлаг, егерь, кастрюля"]'::jsonb where question_id = 5702; -- fipi-2cb9ad2708e2
update answers set correct = '["блистая, нагревая, дыша, задумавшись"]'::jsonb where question_id = 4112; -- fipi-25f8fa048373
update answers set correct = '["суда, болгары, крюки, люди"]'::jsonb where question_id = 5084; -- fipi-c85b8a8c991d
update answers set correct = '["шампиньон, гарсон, Эрмитаж, метрополитен"]'::jsonb where question_id = 5714; -- fipi-742f46048561
update answers set correct = '["кладу, клал, положишь, положите"]'::jsonb where question_id = 4785; -- fipi-d06506689c7f
update answers set correct = '["панорама, президиум, монополия, ихтиология"]'::jsonb where question_id = 4839; -- fipi-c932d6757b03
update answers set correct = '["фонетика, орфоэпия, лексика, грамматика"]'::jsonb where question_id = 4523; -- fipi-3a0a7c4c0c4d
update answers set correct = '["отзыв о книге, рецензия на книгу, удивляться красоте, восхищаться красотой"]'::jsonb where question_id = 5129; -- fipi-14094ad18c5a
update answers set correct = '["сзади, навстречу, вдруг"]'::jsonb where question_id = 4214; -- fipi-7189d933576e
update answers set correct = '["чтоб, и"]'::jsonb where question_id = 4234; -- fipi-c376e03a3cc8
update answers set correct = '["часто, всегда"]'::jsonb where question_id = 4156; -- fipi-4e10c30ab109
update answers set correct = '["разве, не, как-то"]'::jsonb where question_id = 4247; -- fipi-dfdfcdc08cf1
update answers set correct = '["именно, бы"]'::jsonb where question_id = 4251; -- fipi-dfdfcdc08cf1
update answers set correct = '["собирать, загорать, озарение"]'::jsonb where question_id = 4474; -- fipi-e79df8e9c752
update answers set correct = '["каждой, каким, иные"]'::jsonb where question_id = 5331; -- fipi-d24aeaeedb0f
update answers set correct = '["Костя, друга, человека"]'::jsonb where question_id = 5531; -- fipi-16f5e8a759da
update answers set correct = '["заведёшь, проведёшь"]'::jsonb where question_id = 5529; -- fipi-16f5e8a759da
update answers set correct = '["школьных, шалостях"]'::jsonb where question_id = 5555; -- fipi-25f64ef7d043
update answers set correct = '["что, важнейшая"]'::jsonb where question_id = 5557; -- fipi-25f64ef7d043
update answers set correct = '["несколько, том, эти"]'::jsonb where question_id = 5620; -- fipi-49866f7be5e4

-- 2) Снять с публикации (17 заданий): либо ссылаются на
-- список вариантов, которого физически нет в данных (потерялся при
-- скрапинге), либо неверно определён тип задания (word вместо choice)
-- без самих вариантов - решить эти задания невозможно физически.
update questions set published = false where id in (321,3189,3680,3685,3705,3799,4168,4205,4282,4376,4540,4791,4820,5039,5057,5566,5571);

-- 3) Полностью пустые тесты (0 заданий вообще, даже черновиков) - удалить
delete from tests where id in ('fipi-5774bb7de9e8', 'fipi-ebb12f5d83b1');