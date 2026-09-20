import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { api, RunResult, Submission } from '../api';

const POLL_INTERVAL_MS = 1000;
const TERMINAL_STATUSES = new Set(['done', 'cancelled', 'system_error']);

/** Витрина учебного элемента (структура курса, автодополнение и т.д. — раздел 5.3/5.5
 * ТЗ) сюда ещё не входит. Здесь — минимальная браузерная IDE для одной задачи по её
 * id, чтобы можно было руками проверить связку run/submit/Checker. */
export default function CoursePage() {
  const { courseId } = useParams();
  const [problemId, setProblemId] = useState('1');
  const [code, setCode] = useState('print("hello")\n');
  const [stdin, setStdin] = useState('');
  const [result, setResult] = useState<RunResult | null>(null);
  const [submission, setSubmission] = useState<Submission | null>(null);
  const [error, setError] = useState('');
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => {
    if (pollTimer.current) clearInterval(pollTimer.current);
  }, []);

  const run = async () => {
    setError('');
    try {
      setResult(await api.run(Number(problemId), code, stdin));
    } catch (e: any) {
      setError(e.message);
    }
  };

  // JDG-001: отправка ставит посылку в очередь — статус приходит асинхронно,
  // опрашиваем GET /submissions/{id} пока воркер её не обработает.
  const submit = async () => {
    setError('');
    setSubmission(null);
    if (pollTimer.current) clearInterval(pollTimer.current);
    try {
      const created = await api.submit(Number(problemId), code);
      setSubmission(created);
      pollTimer.current = setInterval(async () => {
        try {
          const updated = await api.getSubmission(created.id);
          setSubmission(updated);
          if (TERMINAL_STATUSES.has(updated.status) && pollTimer.current) {
            clearInterval(pollTimer.current);
          }
        } catch (e: any) {
          setError(e.message);
          if (pollTimer.current) clearInterval(pollTimer.current);
        }
      }, POLL_INTERVAL_MS);
    } catch (e: any) {
      setError(e.message);
    }
  };

  return (
    <div className="page">
      <h1>Курс #{courseId}</h1>
      <label>
        ID задачи (ProblemRevision):
        <input value={problemId} onChange={(e) => setProblemId(e.target.value)} />
      </label>
      <textarea className="code" value={code} onChange={(e) => setCode(e.target.value)} rows={12} />
      <label>
        stdin для «Запустить»:
        <input value={stdin} onChange={(e) => setStdin(e.target.value)} />
      </label>
      <div className="actions">
        <button onClick={run}>Запустить</button>
        <button onClick={submit}>Отправить</button>
      </div>
      {error && <p className="error">{error}</p>}
      {result && (
        <pre className="output">
          stdout: {result.stdout}
          {'\n'}stderr: {result.stderr}
          {result.timed_out ? '\n(превышено время выполнения)' : ''}
        </pre>
      )}
      {submission && (
        <pre className="output">
          статус: {submission.status}
          {submission.verdict ? `\nвердикт: ${submission.verdict}` : ''}
          {submission.score !== null ? `\nбалл: ${submission.score}` : ''}
          {!TERMINAL_STATUSES.has(submission.status) ? '\n(проверяется…)' : ''}
        </pre>
      )}
    </div>
  );
}
