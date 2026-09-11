// Каталог тестов: фильтр по классам и разделам подготовки к экзаменам.

const LEVEL_NAMES = { 1: 'базовый', 2: 'средний', 3: 'сложный' };

let catalogData = null;
let activeSection = 'all';

// Карточка одного теста.
function renderTestCard(test) {
  const card = document.createElement('a');
  card.className = 'test-card';
  card.href = 'test.html?id=' + encodeURIComponent(test.id);

  const topic = document.createElement('span');
  topic.className = 'test-card__topic';
  topic.textContent = test.topic;

  const title = document.createElement('span');
  title.className = 'test-card__title';
  title.textContent = test.title;

  const meta = document.createElement('span');
  meta.className = 'test-card__meta';

  const count = document.createElement('span');
  count.className = 'badge';
  count.textContent = test.count + ' заданий';

  const level = document.createElement('span');
  level.className = 'badge badge--level-' + test.level;
  level.textContent = LEVEL_NAMES[test.level] || 'уровень ' + test.level;

  meta.append(count, level);
  card.append(topic, title, meta);

  return card;
}

// Группирует тесты по теме, сохраняя порядок первого появления темы.
function groupByTopic(tests) {
  const order = [];
  const groups = {};

  tests.forEach(function (test) {
    if (!groups[test.topic]) {
      groups[test.topic] = [];
      order.push(test.topic);
    }
    groups[test.topic].push(test);
  });

  return order.map(function (topic) { return { topic: topic, tests: groups[topic] }; });
}

// Блок одного раздела со списком тестов, подгруппированных по темам —
// при сотнях тестов в разделе плоский список стал бы нечитаемым.
function renderSection(section, tests) {
  const block = document.createElement('section');
  block.className = 'section';

  const title = document.createElement('h2');
  title.className = 'section__title';
  title.textContent = section.title;
  block.append(title);

  if (tests.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'section__empty';
    empty.textContent = 'В этом разделе тестов пока нет';
    block.append(empty);
    return block;
  }

  groupByTopic(tests).forEach(function (group) {
    const topicTitle = document.createElement('h3');
    topicTitle.className = 'topic-title';
    topicTitle.textContent = group.topic;
    block.append(topicTitle);

    const grid = document.createElement('div');
    grid.className = 'test-grid';
    group.tests.forEach(function (test) { grid.append(renderTestCard(test)); });
    block.append(grid);
  });

  return block;
}

function renderCatalog() {
  const catalog = document.querySelector('.catalog');
  catalog.textContent = '';

  const sections = catalogData.sections.filter(function (section) {
    return activeSection === 'all' || section.id === activeSection;
  });

  sections.forEach(function (section) {
    const tests = catalogData.tests.filter(function (test) {
      return test.section === section.id;
    });

    // В режиме «Все разделы» пустые разделы не показываем, чтобы не было
    // длинного списка заглушек. При выборе конкретного — показываем всегда.
    if (activeSection === 'all' && tests.length === 0) return;

    catalog.append(renderSection(section, tests));
  });

  if (!catalog.children.length) {
    const empty = document.createElement('p');
    empty.className = 'section__empty';
    empty.textContent = 'Тесты пока не добавлены';
    catalog.append(empty);
  }
}

function renderFilters() {
  const nav = document.querySelector('.filters');
  const items = [{ id: 'all', title: 'Все разделы' }].concat(catalogData.sections);

  items.forEach(function (item) {
    const button = document.createElement('button');
    button.className = 'filter' + (item.id === activeSection ? ' filter--active' : '');
    button.type = 'button';
    button.textContent = item.title;

    button.addEventListener('click', function () {
      activeSection = item.id;
      nav.querySelectorAll('.filter').forEach(function (other) {
        other.classList.remove('filter--active');
      });
      button.classList.add('filter--active');
      renderCatalog();
    });

    nav.append(button);
  });
}

async function initCatalog() {
  const [{ data: sections }, { data: tests }] = await Promise.all([
    supabaseClient.from('sections').select('*').order('sort_order'),
    supabaseClient.from('tests').select('*, questions(count)').order('title')
  ]);

  catalogData = {
    sections: sections,
    tests: tests.map(function (test) {
      return {
        id: test.id,
        title: test.title,
        section: test.section,
        topic: test.topic,
        level: test.level,
        count: test.questions[0] ? test.questions[0].count : 0
      };
    })
  };

  renderFilters();
  renderCatalog();
}

initCatalog();
