import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, Course, Me } from './api';

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [courses, setCourses] = useState<Course[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    api
      .me()
      .then(setMe)
      .catch(() => setError('Не авторизован — войдите через портал (SSO)'));
    api.courses().then(setCourses).catch(() => {});
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
      <h2>Курсы</h2>
      <ul>
        {courses.map((c) => (
          <li key={c.id}>
            <Link to={`/courses/${c.id}`}>{c.title}</Link>
          </li>
        ))}
        {courses.length === 0 && <li>Пока нет доступных курсов</li>}
      </ul>
    </div>
  );
}
