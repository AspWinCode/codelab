import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { api, RunResult } from '../api';

/** Витрина учебного элемента (структура курса, автодополнение и т.д. — раздел 5.3/5.5
 * ТЗ) сюда ещё не входит. Здесь — минимальная браузерная IDE для одной задачи по её
 * id, чтобы можно было руками проверить связку run/submit/Checker. */
export default function CoursePage() {
  const { courseId } = useParams();
  const [problemId, setProblemId] = useState('1');
  const [code, setCode] = useState('print("hello")\n');
  const [stdin, setStdin] = useState('');
  const [result, setResult] = useState<RunResult | null>(null);
  const [submitResult, setSubmitResult] = useState<any>(null);
  const [error, setError] = useState('');

  const run = async () => {
    setError('');
    try {
      setResult(await api.run(Number(problemId), code, stdin));
    } catch (e: any) {
      setError(e.message);
    }
  };

  const submit = async () => {
    setError('');
    try {
      setSubmitResult(await api.submit(Number(problemId), code));
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
      {submitResult && <pre className="output">{JSON.stringify(submitResult, null, 2)}</pre>}
    </div>
  );
}
