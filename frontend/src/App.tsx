import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, Course, Dashboard, Me } from './api';

const formatDeadline = (iso: string) => new Date(iso).toLocaleDateString('ru-RU');

/** STU-001: главная страница ученика — активные курсы, процент прохождения,
 * ближайшие дедлайны, последние результаты, следующий рекомендуемый шаг.
 * Для не-студентов (методист/тренер/админ, если такой role когда-нибудь тут
 * авторизуется) — просто список курсов без персонального прогресса. */
export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [courses, setCourses] = useState<Course[]>([]);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api
      .me()
      .then((m) => {
        setMe(m);
        if (m.role === 'student') {
          api.dashboard().then(setDashboard).catch(() => {});
        } else {
          api.courses().then(setCourses).catch(() => {});
        }
      })
      .catch(() => setError('Не авторизован — войдите через портал (SSO)'));
  }, []);

  if (error) {
    return <div className="page">{error}</div>;
  }

  return (
    <div className="page">
      <h1>Codelab</h1>
      {me && (
        <p>
          Привет, {me.full_name}
          {me.groups.length > 0 ? ` · ${me.groups.join(', ')}` : ''}
        </p>
      )}

      {me?.role === 'student' ? (
        <>
          <h2>Мои курсы</h2>
          {!dashboard || dashboard.courses.length === 0 ? (
            <p>Пока нет назначенных курсов.</p>
          ) : (
            dashboard.courses.map((c) => (
              <div key={c.course_id} className="output" style={{ marginBottom: 12 }}>
                <Link to={c.last_item_id ? `/courses/${c.course_id}?item=${c.last_item_id}` : `/courses/${c.course_id}`}>
                  <strong>{c.title}</strong>
                </Link>
                <div style={{ marginTop: 6 }}>
                  {c.completed_items} / {c.total_items} заданий · {c.percent}%
                  {c.deadline ? ` · дедлайн: ${formatDeadline(c.deadline)}` : ''}
                </div>
                {c.next_item && (
                  <div style={{ marginTop: 6 }}>
                    Дальше: <Link to={`/courses/${c.course_id}?item=${c.next_item.id}`}>{c.next_item.title}</Link>
                  </div>
                )}
              </div>
            ))
          )}

          <h2>Последние результаты</h2>
          {!dashboard || dashboard.recent_results.length === 0 ? (
            <p>Пока нет проверенных посылок.</p>
          ) : (
            <ul>
              {dashboard.recent_results.map((r) => (
                <li key={r.submission_id}>
                  {r.task_title} — {r.verdict || 'проверяется'}
                  {r.score !== null ? ` (${r.score})` : ''}
                </li>
              ))}
            </ul>
          )}
        </>
      ) : (
        <>
          <h2>Курсы</h2>
          <ul>
            {courses.map((c) => (
              <li key={c.id}>
                <Link to={`/courses/${c.id}`}>{c.title}</Link>
              </li>
            ))}
            {courses.length === 0 && <li>Пока нет доступных курсов</li>}
          </ul>
        </>
      )}
    </div>
  );
}
