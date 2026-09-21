import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, Course, Dashboard, Me, Notification, NotificationPreference } from './api';

const formatDeadline = (iso: string) => new Date(iso).toLocaleDateString('ru-RU');

/** NTF-001/003: колокольчик уведомлений + настройка необязательных типов. */
function NotificationsPanel() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [prefs, setPrefs] = useState<NotificationPreference[]>([]);
  const [open, setOpen] = useState(false);

  const load = () => {
    api.notifications().then(setNotifications).catch(() => {});
    api.notificationPreferences().then(setPrefs).catch(() => {});
  };

  useEffect(() => { load(); }, []);

  const unreadCount = notifications.filter((n) => !n.is_read).length;

  const markRead = async (id: number) => {
    await api.markNotificationRead(id).catch(() => {});
    setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, is_read: true } : n)));
  };

  const togglePref = async (type: string, enabled: boolean) => {
    await api.updateNotificationPreference(type, enabled).catch(() => {});
    setPrefs((prev) => prev.map((p) => (p.type === type ? { ...p, enabled } : p)));
  };

  return (
    <div style={{ marginBottom: 16 }}>
      <button onClick={() => setOpen((o) => !o)}>
        🔔 Уведомления{unreadCount > 0 ? ` (${unreadCount})` : ''}
      </button>
      {open && (
        <div className="output" style={{ marginTop: 8 }}>
          {notifications.length === 0 && <p>Уведомлений пока нет.</p>}
          {notifications.map((n) => (
            <div
              key={n.id}
              style={{ padding: '6px 0', borderBottom: '1px solid #333', opacity: n.is_read ? 0.6 : 1, cursor: n.is_read ? 'default' : 'pointer' }}
              onClick={() => !n.is_read && markRead(n.id)}
            >
              <strong>{n.title}</strong>
              {n.body && <div style={{ fontSize: '0.9em' }}>{n.body}</div>}
              <div style={{ fontSize: '0.8em', color: '#9ca3af' }}>{new Date(n.created_at).toLocaleString('ru-RU')}</div>
            </div>
          ))}
          <div style={{ marginTop: 12, fontSize: '0.85em' }}>
            {prefs.filter((p) => !p.mandatory).map((p) => (
              <label key={p.type} style={{ display: 'block', marginTop: 4 }}>
                <input type="checkbox" checked={p.enabled} onChange={(e) => togglePref(p.type, e.target.checked)} />
                {' '}Напоминание о дедлайне
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

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
      {me && <NotificationsPanel />}

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
