// Админка: вход единственного админа + CRUD тестов и заданий.
// Все данные читаются/пишутся напрямую в Supabase — доступ на запись
// разрешён политиками RLS только авторизованному пользователю
// (см. supabase/schema.sql).

const TYPE_LABELS = {
  choice: 'Выбор варианта',
  'sentence-number': 'Номер предложения',
  word: 'Слово / словосочетание',
  digits: 'Цифры'
};

let sectionsCache = [];
let currentTestId = null;

const views = {
  login: document.querySelector('.login-view'),
  tests: document.querySelector('.tests-view'),
  testForm: document.querySelector('.test-form-view'),
  questions: document.querySelector('.questions-view'),
  questionForm: document.querySelector('.question-form-view')
};

function showView(name) {
  Object.keys(views).forEach(function (key) {
    views[key].hidden = key !== name;
  });
}

// ---------- Аутентификация ----------

async function refreshAuthUi() {
  const { data: { session } } = await supabaseClient.auth.getSession();
  const logoutButton = document.querySelector('.logout-button');

  if (session) {
    logoutButton.hidden = false;
    await loadSections();
    await showTestsView();
  } else {
    logoutButton.hidden = true;
    showView('login');
  }
}

document.querySelector('.login-form').addEventListener('submit', async function (event) {
  event.preventDefault();
  const form = event.target;
  const errorEl = document.querySelector('.login-error');
  errorEl.hidden = true;

  const { error } = await supabaseClient.auth.signInWithPassword({
    email: form.email.value.trim(),
    password: form.password.value
  });

  if (error) {
    errorEl.textContent = 'Не удалось войти: проверьте email и пароль.';
    errorEl.hidden = false;
    return;
  }

  form.reset();
  refreshAuthUi();
});

document.querySelector('.logout-button').addEventListener('click', async function () {
  await supabaseClient.auth.signOut();
  refreshAuthUi();
});

// ---------- Разделы (для селекта в форме теста) ----------

async function loadSections() {
  const { data } = await supabaseClient.from('sections').select('*').order('sort_order');
  sectionsCache = data || [];

  const select = document.querySelector('select[name="section"]');
  select.innerHTML = '';
  sectionsCache.forEach(function (section) {
    const option = document.createElement('option');
    option.value = section.id;
    option.textContent = section.title;
    select.append(option);
  });
}

function sectionTitle(id) {
  const section = sectionsCache.find(function (s) { return s.id === id; });
  return section ? section.title : id;
}

// ---------- Список тестов ----------

async function showTestsView() {
  showView('tests');
  const list = document.querySelector('.tests-list');
  list.textContent = 'Загрузка…';

  const { data: tests } = await supabaseClient
    .from('tests')
    .select('*, questions(count)')
    .order('title');

  list.textContent = '';

  if (!tests || tests.length === 0) {
    list.textContent = 'Тестов пока нет — добавьте первый.';
    return;
  }

  tests.forEach(function (test) {
    const row = document.createElement('div');
    row.className = 'admin-row';

    const info = document.createElement('div');
    info.className = 'admin-row__info';

    const title = document.createElement('span');
    title.className = 'admin-row__title';
    title.textContent = test.title;

    const meta = document.createElement('span');
    meta.className = 'admin-row__meta';
    const count = test.questions[0] ? test.questions[0].count : 0;
    meta.textContent = sectionTitle(test.section) + ' · ' + test.topic + ' · ' + count + ' заданий';

    info.append(title, meta);

    const actions = document.createElement('div');
    actions.className = 'admin-row__actions';

    const openButton = document.createElement('button');
    openButton.className = 'button button--ghost';
    openButton.type = 'button';
    openButton.textContent = 'Задания';
    openButton.addEventListener('click', function () { showQuestionsView(test); });

    const editButton = document.createElement('button');
    editButton.className = 'button button--ghost';
    editButton.type = 'button';
    editButton.textContent = 'Изменить';
    editButton.addEventListener('click', function () { showTestForm(test); });

    actions.append(openButton, editButton);
    row.append(info, actions);
    list.append(row);
  });
}

document.querySelector('.add-test-button').addEventListener('click', function () {
  showTestForm(null);
});

document.querySelectorAll('.back-to-tests').forEach(function (button) {
  button.addEventListener('click', showTestsView);
});

// ---------- Форма теста ----------

function showTestForm(test) {
  showView('testForm');
  const form = document.querySelector('.test-form');
  form.reset();

  document.querySelector('.test-form-title').textContent = test ? 'Изменить тест' : 'Новый тест';
  form.id.value = test ? test.id : '';
  form.title.value = test ? test.title : '';
  form.section.value = test ? test.section : sectionsCache[0].id;
  form.topic.value = test ? test.topic : '';
  form.level.value = test ? String(test.level) : '1';

  document.querySelector('.delete-test-button').hidden = !test;
}

document.querySelector('.test-form').addEventListener('submit', async function (event) {
  event.preventDefault();
  const form = event.target;
  const existingId = form.id.value;

  const payload = {
    title: form.title.value.trim(),
    section: form.section.value,
    topic: form.topic.value.trim(),
    level: Number(form.level.value)
  };

  if (existingId) {
    await supabaseClient.from('tests').update(payload).eq('id', existingId);
  } else {
    payload.id = 'test-' + Date.now().toString(36);
    await supabaseClient.from('tests').insert(payload);
  }

  showTestsView();
});

document.querySelector('.delete-test-button').addEventListener('click', async function () {
  const id = document.querySelector('.test-form').id.value;
  if (!id) return;
  if (!confirm('Удалить тест целиком, вместе со всеми заданиями?')) return;

  await supabaseClient.from('tests').delete().eq('id', id);
  showTestsView();
});

// ---------- Список заданий теста ----------

async function showQuestionsView(test) {
  currentTestId = test.id;
  showView('questions');
  document.querySelector('.questions-title').textContent = test.title;

  const list = document.querySelector('.questions-list');
  list.textContent = 'Загрузка…';

  const { data: questions } = await supabaseClient
    .from('questions')
    .select('*')
    .eq('test_id', test.id)
    .order('position');

  list.textContent = '';

  if (!questions || questions.length === 0) {
    list.textContent = 'Заданий пока нет — добавьте первое.';
    return;
  }

  questions.forEach(function (question, index) {
    const row = document.createElement('div');
    row.className = 'admin-row';

    const info = document.createElement('div');
    info.className = 'admin-row__info';

    const title = document.createElement('span');
    title.className = 'admin-row__title';
    title.textContent = (index + 1) + '. ' + question.text;

    const meta = document.createElement('span');
    meta.className = 'admin-row__meta';
    meta.textContent = TYPE_LABELS[question.type] || question.type;

    info.append(title, meta);

    const actions = document.createElement('div');
    actions.className = 'admin-row__actions';

    const editButton = document.createElement('button');
    editButton.className = 'button button--ghost';
    editButton.type = 'button';
    editButton.textContent = 'Изменить';
    editButton.addEventListener('click', function () { showQuestionForm(test, question); });

    actions.append(editButton);
    row.append(info, actions);
    list.append(row);
  });
}

document.querySelector('.add-question-button').addEventListener('click', function () {
  showQuestionForm({ id: currentTestId }, null);
});

document.querySelectorAll('.back-to-questions').forEach(function (button) {
  button.addEventListener('click', function () {
    showQuestionsView({ id: currentTestId, title: document.querySelector('.questions-title').textContent });
  });
});

// ---------- Форма задания ----------

function renderOptionRows(options, correctIndex) {
  const list = document.querySelector('.options-list');
  list.textContent = '';

  const values = options && options.length ? options : ['', '', '', '', ''];

  values.forEach(function (value, index) {
    const row = document.createElement('div');
    row.className = 'option-row';

    const radio = document.createElement('input');
    radio.type = 'radio';
    radio.name = 'correctOption';
    radio.value = String(index);
    radio.checked = index === correctIndex;

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'field__input';
    input.value = value;
    input.placeholder = 'Вариант ' + String.fromCharCode(1040 + index);

    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.className = 'option-row__remove';
    removeButton.textContent = '✕';
    removeButton.title = 'Удалить вариант';
    removeButton.addEventListener('click', function () { row.remove(); });

    row.append(radio, input, removeButton);
    list.append(row);
  });
}

document.querySelector('.options-field').insertAdjacentHTML(
  'beforeend',
  '<button type="button" class="add-option-button">+ вариант</button>'
);
document.querySelector('.add-option-button').addEventListener('click', function () {
  const list = document.querySelector('.options-list');
  const index = list.children.length;
  const row = document.createElement('div');
  row.className = 'option-row';
  row.innerHTML =
    '<input type="radio" name="correctOption" value="' + index + '">' +
    '<input type="text" class="field__input" placeholder="Вариант ' + String.fromCharCode(1040 + index) + '">' +
    '<button type="button" class="option-row__remove" title="Удалить вариант">✕</button>';
  row.querySelector('.option-row__remove').addEventListener('click', function () { row.remove(); });
  list.append(row);
});

const ANSWER_HINTS = {
  'sentence-number': 'Номер предложения. Через запятую — если подходит несколько.',
  word: 'Слово или словосочетание. Через запятую — если подходит несколько вариантов.',
  digits: 'Цифры одной строкой, например: 134 — порядок цифр не важен при проверке.'
};

function updateQuestionFormFields() {
  const type = document.querySelector('select[name="type"]').value;
  const isChoice = type === 'choice';

  document.querySelector('.options-field').hidden = !isChoice;
  document.querySelector('.answer-field').hidden = isChoice;
  document.querySelector('.hint-field').hidden = isChoice;
  document.querySelector('.answer-field__hint').textContent = ANSWER_HINTS[type] || '';
}

document.querySelector('select[name="type"]').addEventListener('change', updateQuestionFormFields);

async function showQuestionForm(test, question) {
  currentTestId = test.id;
  showView('questionForm');

  const form = document.querySelector('.question-form');
  form.reset();
  form.test_id.value = test.id;
  form.id.value = question ? question.id : '';

  document.querySelector('.delete-question-button').hidden = !question;

  if (question) {
    form.type.value = question.type;
    form.text.value = question.text;
    form.passage.value = question.passage || '';
    form.hint.value = question.hint || '';

    if (question.type === 'choice') {
      const { data: answer } = await supabaseClient
        .from('answers').select('*').eq('question_id', question.id).maybeSingle();
      const correctIndex = answer && typeof answer.correct[0] === 'number' ? answer.correct[0] : -1;
      renderOptionRows(question.options, correctIndex);
    } else {
      const { data: answer } = await supabaseClient
        .from('answers').select('*').eq('question_id', question.id).maybeSingle();
      form.answer.value = answer ? answer.correct.join(', ') : '';
      renderOptionRows(null, -1);
    }
  } else {
    form.type.value = 'choice';
    renderOptionRows(null, -1);
  }

  updateQuestionFormFields();
}

document.querySelector('.question-form').addEventListener('submit', async function (event) {
  event.preventDefault();
  const form = event.target;
  const type = form.type.value;
  const existingId = form.id.value;
  const testId = form.test_id.value;

  let options = null;
  let correct;
  let digitSet = false;

  if (type === 'choice') {
    const rows = Array.from(document.querySelectorAll('.option-row'));
    options = rows.map(function (row) { return row.querySelector('input[type="text"]').value.trim(); })
      .filter(function (value) { return value !== ''; });

    const checkedRadio = document.querySelector('input[name="correctOption"]:checked');
    if (!checkedRadio) {
      alert('Отметьте, какой вариант правильный.');
      return;
    }
    correct = [Number(checkedRadio.value)];
  } else {
    correct = form.answer.value.split(',').map(function (v) { return v.trim(); }).filter(Boolean);
    if (correct.length === 0) {
      alert('Укажите верный ответ.');
      return;
    }
    digitSet = type === 'digits';
  }

  const questionPayload = {
    test_id: testId,
    type: type,
    text: form.text.value.trim(),
    passage: form.passage.value.trim() || null,
    options: options,
    hint: type === 'choice' ? null : (form.hint.value.trim() || null)
  };

  let questionId = existingId ? Number(existingId) : null;

  if (questionId) {
    await supabaseClient.from('questions').update(questionPayload).eq('id', questionId);
  } else {
    const { count } = await supabaseClient
      .from('questions').select('id', { count: 'exact', head: true }).eq('test_id', testId);
    questionPayload.position = (count || 0) + 1;

    const { data: inserted } = await supabaseClient
      .from('questions').insert(questionPayload).select('id').single();
    questionId = inserted.id;
  }

  await supabaseClient.from('answers').upsert({
    question_id: questionId,
    correct: correct,
    digit_set: digitSet
  });

  const { data: test } = await supabaseClient.from('tests').select('*').eq('id', testId).single();
  showQuestionsView(test);
});

document.querySelector('.delete-question-button').addEventListener('click', async function () {
  const id = document.querySelector('.question-form').id.value;
  if (!id) return;
  if (!confirm('Удалить это задание?')) return;

  await supabaseClient.from('questions').delete().eq('id', id);
  const { data: test } = await supabaseClient.from('tests').select('*').eq('id', currentTestId).single();
  showQuestionsView(test);
});

refreshAuthUi();
