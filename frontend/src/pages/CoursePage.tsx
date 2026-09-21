import { useEffect, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { api, LearningItemTree, RunResult, Submission } from '../api';
import { renderContentHtml } from '../utils/renderContent';

const POLL_INTERVAL_MS = 1000;
const TERMINAL_STATUSES = new Set(['done', 'cancelled', 'system_error']);

const TYPE_LABEL: Record<string, string> = {
  theory: 'Теория', video: 'Видео', file: 'Файл', link: 'Ссылка',
  quiz: 'Тест', task: 'Задача', manual: 'Ручное задание', checkpoint: 'Контрольная точка',
};

function flatten(items: LearningItemTree[]): LearningItemTree[] {
  return items.flatMap((i) => [i, ...flatten(i.children)]);
}

function TreeNode({ item, depth, selectedId, onSelect }: {
  item: LearningItemTree; depth: number; selectedId: number | null; onSelect: (i: LearningItemTree) => void;
}) {
  const locked = !item.unlocked;
  return (
    <div style={{ marginLeft: depth * 16 }}>
      <div
        onClick={() => !locked && onSelect(item)}
        style={{
          padding: '6px 8px',
          borderRadius: 6,
          cursor: locked ? 'not-allowed' : 'pointer',
          opacity: locked ? 0.45 : 1,
          background: selectedId === item.id ? 'rgba(59,130,246,0.2)' : 'transparent',
        }}
      >
        {item.completed ? '✅ ' : locked ? '🔒 ' : '▫️ '}
        <strong>{item.title}</strong>
        <span style={{ color: '#9ca3af', marginLeft: 6, fontSize: '0.85em' }}>{TYPE_LABEL[item.type] || item.type}</span>
      </div>
      {item.children.map((c) => (
        <TreeNode key={c.id} item={c} depth={depth + 1} selectedId={selectedId} onSelect={onSelect} />
      ))}
    </div>
  );
}

/** STU-002: структура курса, статусы элементов, доступность заблокированных
 * (LMS-004). STU-004: история попыток по выбранной задаче. STU-005: последняя
 * открытая позиция сохраняется на сервере и подставляется через ?item=. */
export default function CoursePage() {
  const { courseId } = useParams();
  const [searchParams] = useSearchParams();
  const [tree, setTree] = useState<LearningItemTree[]>([]);
  const [selected, setSelected] = useState<LearningItemTree | null>(null);
  const [code, setCode] = useState('print("hello")\n');
  const [stdin, setStdin] = useState('');
  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const [submission, setSubmission] = useState<Submission | null>(null);
  const [history, setHistory] = useState<Submission[]>([]);
  const [error, setError] = useState('');
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    api.getTree(Number(courseId)).then((t) => {
      setTree(t);
      const wantedId = Number(searchParams.get('item'));
      const flat = flatten(t);
      const initial = flat.find((i) => i.id === wantedId) || flat.find((i) => i.type === 'task' && i.unlocked);
      if (initial) selectItem(initial);
    }).catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId]);

  useEffect(() => () => {
    if (pollTimer.current) clearInterval(pollTimer.current);
  }, []);

  const selectItem = (item: LearningItemTree) => {
    setSelected(item);
    setRunResult(null);
    setSubmission(null);
    setHistory([]);
    api.setLastPosition(Number(courseId), item.id).catch(() => {});
    if (item.type === 'task' && item.problem_revision_id) {
      api.mySubmissions(item.problem_revision_id).then(setHistory).catch(() => {});
    }
  };

  const run = async () => {
    if (!selected?.problem_revision_id) return;
    setError('');
    try {
      setRunResult(await api.run(selected.problem_revision_id, code, stdin));
    } catch (e: any) {
      setError(e.message);
    }
  };

  const submit = async () => {
    if (!selected?.problem_revision_id) return;
    setError('');
    setSubmission(null);
    if (pollTimer.current) clearInterval(pollTimer.current);
    try {
      const created = await api.submit(selected.problem_revision_id, code);
      setSubmission(created);
      pollTimer.current = setInterval(async () => {
        try {
          const updated = await api.getSubmission(created.id);
          setSubmission(updated);
          if (TERMINAL_STATUSES.has(updated.status)) {
            if (pollTimer.current) clearInterval(pollTimer.current);
            if (selected.problem_revision_id) {
              api.mySubmissions(selected.problem_revision_id).then(setHistory).catch(() => {});
            }
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
    <div className="page" style={{ maxWidth: 1100, display: 'flex', gap: 24 }}>
      <div style={{ width: 280, flexShrink: 0 }}>
        <h1 style={{ fontSize: '1.2em' }}>Курс #{courseId}</h1>
        {tree.map((item) => (
          <TreeNode key={item.id} item={item} depth={0} selectedId={selected?.id ?? null} onSelect={selectItem} />
        ))}
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        {error && <p className="error">{error}</p>}
        {!selected && <p>Выберите элемент курса слева.</p>}

        {selected && selected.type !== 'task' && (
          <div>
            <h2>{selected.title}</h2>
            <div
              className="preview"
              dangerouslySetInnerHTML={{ __html: renderContentHtml(selected.content || selected.description || '') }}
            />
          </div>
        )}

        {selected && selected.type === 'task' && (
          <div>
            <h2>{selected.title}</h2>
            <textarea className="code" rows={14} value={code} onChange={(e) => setCode(e.target.value)} />
            <label>
              stdin для «Запустить»:
              <input value={stdin} onChange={(e) => setStdin(e.target.value)} />
            </label>
            <div className="actions">
              <button onClick={run}>Запустить</button>
              <button onClick={submit}>Отправить</button>
            </div>
            {runResult && (
              <pre className="output">
                stdout: {runResult.stdout}
                {'\n'}stderr: {runResult.stderr}
                {runResult.timed_out ? '\n(превышено время выполнения)' : ''}
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

            {history.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <h3>История попыток</h3>
                {history.map((s) => (
                  <div key={s.id} className="output" style={{ marginBottom: 8 }}>
                    {new Date(s.created_at).toLocaleString('ru-RU')} — {s.verdict || s.status}
                    {s.score !== null ? ` (${s.score})` : ''}
                    {s.manual_comment && (
                      <div style={{ color: '#9ca3af', marginTop: 4 }}>Комментарий: {s.manual_comment}</div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
