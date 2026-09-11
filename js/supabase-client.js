// Единая точка подключения к Supabase. Ключ — публичный anon-ключ,
// его безопасно светить в коде клиента: запись данных закрыта
// политиками доступа (RLS) и требует входа админа, а таблица с
// правильными ответами вообще не читается напрямую (см. supabase/schema.sql).

const SUPABASE_URL = 'https://mypjlvxvcpsajaibjvwo.supabase.co';
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im15cGpsdnh2Y3BzYWphaWJqdndvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODkxMTc1NTksImV4cCI6MjEwNDY5MzU1OX0.ubtqCKZ3wyUm3k-Y2tQT-6bqDLKZV7MH22_AouDAmAk';

const supabaseClient = supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
