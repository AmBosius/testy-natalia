// Проверка ответов вынесена в отдельный модуль намеренно.
// Сейчас правильные ответы лежат в отдельном JSON и запрашиваются только
// в момент нажатия «Проверить» — до этого их нет ни в HTML, ни в запросах.
// На этапе подключения Supabase заменяется только тело checkAnswers():
// вместо загрузки файла будет вызов Edge Function, остальной код не меняется.

// Приводит ответ к сравнимому виду: строчные буквы, без пробелов, ё = е.
function normalize(value) {
  return String(value)
    .toLowerCase()
    .replace(/ё/g, 'е')
    .replace(/\s+/g, '')
    .replace(/[.,;:!?]/g, '');
}

// Ответ считается верным, если совпал хотя бы с одним из допустимых вариантов.
function isCorrect(given, accepted) {
  if (given === null || given === undefined || given === '') return false;

  return accepted.some(function (variant) {
    if (typeof variant === 'number') return variant === given;
    return normalize(variant) === normalize(given);
  });
}

async function checkAnswers(testId, userAnswers) {
  const response = await fetch('data/' + testId + '.answers.json');
  if (!response.ok) throw new Error('Не удалось загрузить ответы теста');

  const data = await response.json();
  const result = { total: 0, correct: 0, byQuestion: {} };

  Object.keys(data.answers).forEach(function (questionId) {
    const accepted = data.answers[questionId].correct;
    const given = userAnswers[questionId];
    const ok = isCorrect(given, accepted);

    result.total += 1;
    if (ok) result.correct += 1;
    result.byQuestion[questionId] = { correct: ok, accepted: accepted };
  });

  return result;
}
