// Админка: вход единственного админа + CRUD тестов и заданий.
// Все данные читаются/пишутся напрямую в Supabase — доступ на запись
// разрешён политиками RLS только авторизованному пользователю
// (см. supabase/schema.sql).

const TYPE_LABELS = {
  choice: 'Выбор варианта',
  'multi-choice': 'Выбор нескольких вариантов',
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
  questionForm: document.querySelector('.question-form-view'),
  drafts: document.querySelector('.drafts-view')
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

    if (!question.published) {
      const badge = document.createElement('span');
      badge.className = 'badge badge--review';
      badge.textContent = 'на проверке';
      info.append(badge);
    }

    const actions = document.createElement('div');
    actions.className = 'admin-row__actions';

    if (!question.published) {
      const publishButton = document.createElement('button');
      publishButton.className = 'button button--ghost';
      publishButton.type = 'button';
      publishButton.textContent = 'Опубликовать';
      publishButton.addEventListener('click', async function () {
        await supabaseClient.from('questions').update({ published: true }).eq('id', question.id);
        showQuestionsView(test);
      });
      actions.append(publishButton);
    }

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

// ---------- Черновики (needs_review со всех тестов) ----------

const DRAFTS_PAGE_SIZE = 50;
let draftsOffset = 0;

document.querySelector('.show-drafts-button').addEventListener('click', function () {
  draftsOffset = 0;
  showDraftsView(false);
});

async function showDraftsView(append) {
  showView('drafts');
  const list = document.querySelector('.drafts-list');
  if (!append) list.textContent = 'Загрузка…';

  const { data: questions, count } = await supabaseClient
    .from('questions')
    .select('*, tests(id, title)', { count: 'exact' })
    .eq('published', false)
    .order('id')
    .range(draftsOffset, draftsOffset + DRAFTS_PAGE_SIZE - 1);

  if (!append) list.textContent = '';
  const existingMore = document.querySelector('.drafts-load-more');
  if (existingMore) existingMore.remove();

  if (!questions || questions.length === 0) {
    if (!append) list.textContent = 'Черновиков нет — всё опубликовано.';
    return;
  }

  questions.forEach(function (question) {
    const row = document.createElement('div');
    row.className = 'admin-row';

    const info = document.createElement('div');
    info.className = 'admin-row__info';

    const title = document.createElement('span');
    title.className = 'admin-row__title';
    title.textContent = question.text;

    const meta = document.createElement('span');
    meta.className = 'admin-row__meta';
    meta.textContent = (question.tests ? question.tests.title : question.test_id) +
      ' · ' + (TYPE_LABELS[question.type] || question.type);

    info.append(title, meta);

    const actions = document.createElement('div');
    actions.className = 'admin-row__actions';

    const publishButton = document.createElement('button');
    publishButton.className = 'button button--ghost';
    publishButton.type = 'button';
    publishButton.textContent = 'Опубликовать';
    publishButton.addEventListener('click', async function () {
      await supabaseClient.from('questions').update({ published: true }).eq('id', question.id);
      row.remove();
    });

    const editButton = document.createElement('button');
    editButton.className = 'button button--ghost';
    editButton.type = 'button';
    editButton.textContent = 'Изменить';
    editButton.addEventListener('click', function () {
      showQuestionForm(question.tests || { id: question.test_id }, question);
    });

    actions.append(publishButton, editButton);
    row.append(info, actions);
    list.append(row);
  });

  draftsOffset += questions.length;

  if (count !== null && draftsOffset < count) {
    const moreButton = document.createElement('button');
    moreButton.type = 'button';
    moreButton.className = 'add-option-button drafts-load-more';
    moreButton.textContent = 'Показать ещё (осталось ' + (count - draftsOffset) + ')';
    moreButton.addEventListener('click', function () { showDraftsView(true); });
    list.append(moreButton);
  }
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

// choice -> один правильный вариант (radio), multi-choice -> несколько (checkbox).
function currentOptionInputType() {
  const type = document.querySelector('select[name="type"]').value;
  return type === 'multi-choice' ? 'checkbox' : 'radio';
}

function renderOptionRows(options, correctIndices) {
  const list = document.querySelector('.options-list');
  list.textContent = '';

  const values = options && options.length ? options : ['', '', '', '', ''];
  const correctSet = correctIndices || [];

  values.forEach(function (value, index) {
    const row = document.createElement('div');
    row.className = 'option-row';

    const marker = document.createElement('input');
    marker.type = currentOptionInputType();
    marker.name = 'correctOption';
    marker.value = String(index);
    marker.checked = correctSet.indexOf(index) !== -1;

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

    row.append(marker, input, removeButton);
    list.append(row);
  });
}

// При переключении choice <-> multi-choice меняет radio/checkbox у уже
// введённых вариантов, не теряя текст и отметки.
function applyOptionInputType() {
  const inputType = currentOptionInputType();
  document.querySelectorAll('.option-row input[name="correctOption"]').forEach(function (marker) {
    if (marker.type === inputType) return;
    const replacement = document.createElement('input');
    replacement.type = inputType;
    replacement.name = 'correctOption';
    replacement.value = marker.value;
    replacement.checked = marker.checked;
    marker.replaceWith(replacement);
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
    '<input type="' + currentOptionInputType() + '" name="correctOption" value="' + index + '">' +
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
  const isOptionsType = type === 'choice' || type === 'multi-choice';

  document.querySelector('.options-field').hidden = !isOptionsType;
  document.querySelector('.answer-field').hidden = isOptionsType;
  document.querySelector('.hint-field').hidden = isOptionsType;
  document.querySelector('.answer-field__hint').textContent = ANSWER_HINTS[type] || '';

  if (isOptionsType) applyOptionInputType();
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

    if (question.type === 'choice' || question.type === 'multi-choice') {
      const { data: answer } = await supabaseClient
        .from('answers').select('*').eq('question_id', question.id).maybeSingle();
      const correctIndices = answer ? answer.correct.filter(function (v) { return typeof v === 'number'; }) : [];
      renderOptionRows(question.options, correctIndices);
    } else {
      const { data: answer } = await supabaseClient
        .from('answers').select('*').eq('question_id', question.id).maybeSingle();
      form.answer.value = answer ? answer.correct.join(', ') : '';
      renderOptionRows(null, []);
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

  if (type === 'choice' || type === 'multi-choice') {
    const rows = Array.from(document.querySelectorAll('.option-row'));
    options = rows.map(function (row) { return row.querySelector('input[type="text"]').value.trim(); })
      .filter(function (value) { return value !== ''; });

    const checkedMarkers = document.querySelectorAll('input[name="correctOption"]:checked');
    if (checkedMarkers.length === 0) {
      alert('Отметьте, какой вариант(-ы) правильный.');
      return;
    }
    correct = Array.from(checkedMarkers).map(function (input) { return Number(input.value); });
  } else {
    correct = form.answer.value.split(',').map(function (v) { return v.trim(); }).filter(Boolean);
    if (correct.length === 0) {
      alert('Укажите верный ответ.');
      return;
    }
    digitSet = type === 'digits';
  }

  const isOptionsType = type === 'choice' || type === 'multi-choice';
  const questionPayload = {
    test_id: testId,
    type: type,
    text: form.text.value.trim(),
    passage: form.passage.value.trim() || null,
    options: options,
    hint: isOptionsType ? null : (form.hint.value.trim() || null)
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
