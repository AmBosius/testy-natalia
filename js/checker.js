// Проверка ответов выполняется в Supabase (функция check_test, см.
// supabase/schema.sql) — правильные ответы никогда не приходят на
// клиент до нажатия «Проверить» и не видны через вкладку Network.

async function checkAnswers(testId, userAnswers) {
  const { data, error } = await supabaseClient.rpc('check_test', {
    p_test_id: testId,
    p_answers: userAnswers
  });

  if (error) throw error;
  return data;
}
