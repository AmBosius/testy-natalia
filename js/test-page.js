// Страница прохождения теста: рендер заданий, счётчик прогресса
// и проверка всего блока по кнопке.

const params = new URLSearchParams(window.location.search);
const testId = params.get('id');

let currentTest = null;
let checked = false;

// Рисует одно задание в зависимости от его типа.
function renderQuestion(question, index) {
  const item = document.createElement('article');
  item.className = 'question';
  item.dataset.questionId = question.id;

  const head = document.createElement('div');
  head.className = 'question__head';

  const number = document.createElement('span');
  number.className = 'question__number';
  number.textContent = index + 1;

  const text = document.createElement('p');
  text.className = 'question__text';
  text.textContent = question.text;

  head.append(number, text);
  item.append(head);

  const body = document.createElement('div');
  body.className = 'question__body';
  item.append(body);

  if (question.passage) {
    const passage = document.createElement('p');
    passage.className = 'question__passage';
    passage.textContent = question.passage;
    body.append(passage);
  }

  if (question.type === 'choice' || question.type === 'multi-choice') {
    const isMulti = question.type === 'multi-choice';

    if (isMulti) {
      const note = document.createElement('p');
      note.className = 'question__hint';
      note.textContent = 'Отметьте все подходящие варианты';
      body.append(note);
    }

    const list = document.createElement('div');
    list.className = 'options';

    question.options.forEach(function (option, optionIndex) {
      const label = document.createElement('label');
      label.className = 'option';

      const input = document.createElement('input');
      input.type = isMulti ? 'checkbox' : 'radio';
      input.name = 'q' + question.id;
      input.value = optionIndex;

      const marker = document.createElement('span');
      marker.className = 'option__marker';
      marker.textContent = String.fromCharCode(1040 + optionIndex);

      const caption = document.createElement('span');
      caption.textContent = option;

      label.append(input, marker, caption);
      list.append(label);
    });

    body.append(list);
  } else {
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'answer-input';
    input.name = 'q' + question.id;
    input.autocomplete = 'off';
    input.placeholder =
      question.type === 'sentence-number' ? 'Номер предложения'
      : question.type === 'digits' ? 'Цифры без пробелов, например: 134'
      : 'Ответ';
    body.append(input);

    if (question.hint) {
      const hint = document.createElement('p');
      hint.className = 'question__hint';
      hint.textContent = question.hint;
      body.append(hint);
    }
  }

  const verdict = document.createElement('p');
  verdict.className = 'question__verdict';
  body.append(verdict);

  return item;
}

// Собирает ответы ученика: для выбора варианта — индекс, для ввода — строку.
function collectAnswers() {
  const answers = {};

  currentTest.questions.forEach(function (question) {
    if (question.type === 'choice') {
      const checkedOption = document.querySelector(
        '[name="q' + question.id + '"]:checked'
      );
      answers[question.id] = checkedOption ? Number(checkedOption.value) : null;
    } else if (question.type === 'multi-choice') {
      const checkedOptions = document.querySelectorAll(
        '[name="q' + question.id + '"]:checked'
      );
      answers[question.id] = Array.from(checkedOptions)
        .map(function (input) { return Number(input.value); })
        .sort(function (a, b) { return a - b; });
    } else {
      const input = document.querySelector(
        'input[name="q' + question.id + '"]'
      );
      answers[question.id] = input.value.trim();
    }
  });

  return answers;
}

// Счётчик отвеченных заданий в нижней панели.
function updateProgress() {
  const answers = collectAnswers();
  const total = currentTest.questions.length;
  const answered = Object.keys(answers).filter(function (id) {
    const value = answers[id];
    if (Array.isArray(value)) return value.length > 0;
    return value !== null && value !== '';
  }).length;

  document.querySelector('.progress__value').textContent =
    answered + ' из ' + total;
  document.querySelector('.progress__bar').style.width =
    (answered / total) * 100 + '%';
}

function resultMessage(percent) {
  if (percent === 100) return 'Отличный результат — все задания выполнены верно.';
  if (percent >= 80) return 'Хороший результат. Разберите задания с ошибками.';
  if (percent >= 50) return 'Тему стоит повторить и пройти тест ещё раз.';
  return 'Стоит разобрать правило заново, а затем вернуться к тесту.';
}

// Показывает результат: общий счёт и отметку по каждому заданию.
function showResult(result) {
  currentTest.questions.forEach(function (question) {
    const item = document.querySelector(
      '[data-question-id="' + question.id + '"]'
    );
    const info = result.byQuestion[question.id];
    const verdict = item.querySelector('.question__verdict');

    item.classList.add(info.correct ? 'question--correct' : 'question--wrong');

    if (info.correct) {
      verdict.textContent = 'Верно';
    } else {
      const readable = info.accepted
        .map(function (variant) {
          return typeof variant === 'number' ? question.options[variant] : variant;
        })
        .join(question.type === 'multi-choice' ? ' и ' : ' / ');
      verdict.textContent = 'Неверно. Правильный ответ: ' + readable;
    }
  });

  const percent = Math.round((result.correct / result.total) * 100);
  const summary = document.querySelector('.result');

  summary.hidden = false;
  summary.dataset.tone = percent >= 80 ? 'high' : percent >= 50 ? 'mid' : 'low';
  summary.style.setProperty('--percent', percent);
  summary.querySelector('.result__percent').textContent = percent + '%';
  summary.querySelector('.result__score').textContent =
    'Верно ' + result.correct + ' из ' + result.total;
  summary.querySelector('.result__message').textContent = resultMessage(percent);

  document.querySelector('.actionbar').hidden = true;
  document.querySelectorAll('.questions input').forEach(function (input) {
    input.disabled = true;
  });

  summary.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

async function onCheck() {
  if (checked) return;
  checked = true;

  const button = document.querySelector('.check-button');
  button.disabled = true;
  button.textContent = 'Проверяем…';

  try {
    const result = await checkAnswers(testId, collectAnswers());
    showResult(result);
  } catch (error) {
    console.error('Ошибка проверки ответов:', error);
    checked = false;
    button.disabled = false;
    button.textContent = 'Проверить';
    alert('Не удалось проверить ответы. Попробуйте ещё раз.');
  }
}

async function init() {
  const [{ data: test }, { data: questions }] = await Promise.all([
    supabaseClient.from('tests').select('*, sections(title)').eq('id', testId).single(),
    supabaseClient.from('questions').select('*').eq('test_id', testId).order('position')
  ]);

  currentTest = {
    id: test.id,
    title: test.title,
    section: test.sections.title,
    topic: test.topic,
    questions: questions
  };

  document.title = currentTest.title;
  document.querySelector('.test-title').textContent = currentTest.title;
  document.querySelector('.test-meta').textContent =
    currentTest.section + ' · ' + currentTest.topic;

  const list = document.querySelector('.questions');
  currentTest.questions.forEach(function (question, index) {
    list.append(renderQuestion(question, index));
  });

  list.addEventListener('input', updateProgress);
  list.addEventListener('change', updateProgress);
  updateProgress();

  document.querySelector('.check-button').addEventListener('click', onCheck);
  document.querySelector('.retry-button').addEventListener('click', function () {
    window.location.reload();
  });
}

init();
