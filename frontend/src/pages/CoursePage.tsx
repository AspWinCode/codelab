import { CheckCircle, CloseFullscreen, ExpandLess, ExpandMore, Lock, OpenInFull, RadioButtonUnchecked } from '@mui/icons-material';
import {
  Alert, Box, Button, Checkbox, Chip, Container, Divider, Drawer, FormControlLabel,
  FormGroup, List, ListItemButton, ListItemIcon, ListItemText, Paper, Stack, TextField, Typography,
} from '@mui/material';
import { useEffect, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { api, LearningItemTree, ProblemForStudent, QuizAttempt, RunResult, Submission } from '../api';
import Layout from '../components/Layout';
import { FONT_CODE } from '../theme';
import { renderContentHtml } from '../utils/renderContent';

const POLL_INTERVAL_MS = 1000;
const TERMINAL_STATUSES = new Set(['done', 'cancelled', 'system_error']);
const DRAWER_WIDTH = 300;

const TYPE_LABEL: Record<string, string> = {
  theory: 'Теория', video: 'Видео', file: 'Файл', link: 'Ссылка',
  quiz: 'Тест', task: 'Задача', manual: 'Ручное задание', checkpoint: 'Контрольная точка',
  snap_task: 'Задание Snap!',
};

const SNAP_URL = 'https://snap.tirskix.space';

/** Слева — пошаговая инструкция (стрелки листают steps), справа — статичный
 * iframe Snap!. iframe рендерится безусловно на каждый рендер компонента,
 * поэтому не перемонтируется при листании шагов или переключении полноэкранного
 * режима — сохраняется состояние проекта ученика внутри Snap!. */
function SnapTaskView({ item }: { item: LearningItemTree }) {
  const steps = item.steps || [];
  const [stepIndex, setStepIndex] = useState(0);
  const [snapExpanded, setSnapExpanded] = useState(false);

  useEffect(() => { setStepIndex(0); }, [item.id]);

  const step = steps[stepIndex];

  return (
    <Box sx={{ display: 'flex', height: 'calc(100vh - 64px)', width: '100%' }}>
      <Box
        sx={{
          width: snapExpanded ? 0 : { xs: '100%', md: '42%' },
          minWidth: snapExpanded ? 0 : { md: 340 },
          overflow: 'hidden',
          transition: 'width 0.2s ease',
          borderRight: snapExpanded ? 'none' : '1px solid',
          borderColor: 'divider',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Box sx={{ p: 3, flex: 1, overflowY: 'auto' }}>
          <Typography variant="h2" sx={{ mb: 0.5 }}>{item.title}</Typography>
          {steps.length > 0 && (
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Шаг {stepIndex + 1} из {steps.length}{step?.title ? ` — ${step.title}` : ''}
            </Typography>
          )}
          <Box className="preview" dangerouslySetInnerHTML={{ __html: renderContentHtml(step?.content || '') }} />
        </Box>
        {steps.length > 1 && (
          <Stack direction="row" spacing={1.5} sx={{ p: 2, borderTop: '1px solid', borderColor: 'divider' }}>
            <Button disabled={stepIndex === 0} onClick={() => setStepIndex((i) => i - 1)}>Назад</Button>
            <Button variant="contained" disabled={stepIndex >= steps.length - 1} onClick={() => setStepIndex((i) => i + 1)}>Далее</Button>
          </Stack>
        )}
      </Box>

      <Box sx={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <Stack direction="row" justifyContent="flex-end" sx={{ px: 1.5, py: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
          <Button
            size="small"
            startIcon={snapExpanded ? <CloseFullscreen fontSize="small" /> : <OpenInFull fontSize="small" />}
            onClick={() => setSnapExpanded((v) => !v)}
          >
            {snapExpanded ? 'Показать инструкцию' : 'Snap! на весь экран'}
          </Button>
        </Stack>
        <Box sx={{ flex: 1 }}>
          <iframe
            src={SNAP_URL}
            title="Snap!"
            style={{ width: '100%', height: '100%', border: 'none', display: 'block' }}
          />
        </Box>
      </Box>
    </Box>
  );
}

/** Прохождение теста (type=quiz) — один тип вопроса, несколько правильных
 * ответов (checkbox). key={item.id} на месте использования сбрасывает
 * локальный стейт при переключении на другой тест (та же проблема, что
 * чинили для code-редактора задач — старые отметки не должны переползать
 * на новый тест). */
function QuizView({ item }: { item: LearningItemTree }) {
  const questions = item.quiz_questions || [];
  const [selected, setSelected] = useState<Set<number>[]>(() => questions.map(() => new Set()));
  const [result, setResult] = useState<QuizAttempt | null>(null);
  const [lastAttempt, setLastAttempt] = useState<QuizAttempt | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.myQuizAttempts(item.id)
      .then((attempts) => setLastAttempt(attempts[0] || null))
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id]);

  const toggleOption = (qi: number, oi: number) => {
    setSelected((prev) => {
      const next = prev.map((s) => new Set(s));
      if (next[qi].has(oi)) next[qi].delete(oi); else next[qi].add(oi);
      return next;
    });
  };

  const submit = async () => {
    setSubmitting(true);
    setError('');
    try {
      const attempt = await api.submitQuizAttempt(item.id, selected.map((s) => Array.from(s)));
      setResult(attempt);
      setLastAttempt(attempt);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Typography variant="h2" sx={{ mb: 1 }}>{item.title}</Typography>
      {lastAttempt && !result && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Лучший результат: {lastAttempt.score}%
        </Typography>
      )}
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {result && (
        <Alert severity={result.score === 100 ? 'success' : 'info'} sx={{ mb: 2 }}>
          Результат: {result.score}% правильных ответов
        </Alert>
      )}

      <Stack spacing={2.5}>
        {questions.map((q, qi) => (
          <Paper key={qi} variant="outlined" sx={{ p: 2 }}>
            <Typography sx={{ mb: 1 }}>{qi + 1}. {q.text}</Typography>
            <FormGroup>
              {q.options.map((opt, oi) => (
                <FormControlLabel
                  key={oi}
                  control={<Checkbox checked={selected[qi]?.has(oi) ?? false} onChange={() => toggleOption(qi, oi)} />}
                  label={opt.text}
                />
              ))}
            </FormGroup>
          </Paper>
        ))}
      </Stack>

      <Button variant="contained" sx={{ mt: 3 }} disabled={submitting || questions.length === 0} onClick={submit}>
        Отправить
      </Button>
    </Container>
  );
}

function flatten(items: LearningItemTree[]): LearningItemTree[] {
  return items.flatMap((i) => [i, ...flatten(i.children)]);
}

function TreeNode({ item, depth, selectedId, onSelect }: {
  item: LearningItemTree; depth: number; selectedId: number | null; onSelect: (i: LearningItemTree) => void;
}) {
  const locked = !item.unlocked;
  const hasChildren = item.children.length > 0;
  // Развёрнуто по умолчанию — прежнее поведение (все узлы всегда видны),
  // стрелка только добавляет возможность свернуть, не меняет дефолт.
  const [open, setOpen] = useState(true);

  return (
    <>
      <ListItemButton
        selected={selectedId === item.id}
        disabled={locked}
        onClick={() => !locked && onSelect(item)}
        sx={{ pl: 2 + depth * 2 }}
        dense
      >
        <ListItemIcon sx={{ minWidth: 30 }}>
          {item.completed ? <CheckCircle fontSize="small" color="success" /> : locked ? <Lock fontSize="small" /> : <RadioButtonUnchecked fontSize="small" />}
        </ListItemIcon>
        <ListItemText
          primary={item.title}
          secondary={TYPE_LABEL[item.type] || item.type}
          primaryTypographyProps={{ fontSize: '0.9rem', fontWeight: 500 }}
          secondaryTypographyProps={{ fontSize: '0.75rem' }}
        />
        {hasChildren && (
          <ListItemIcon
            sx={{ minWidth: 24, justifyContent: 'flex-end', cursor: 'pointer' }}
            onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
          >
            {open ? <ExpandLess fontSize="small" /> : <ExpandMore fontSize="small" />}
          </ListItemIcon>
        )}
      </ListItemButton>
      {hasChildren && open && item.children.map((c) => (
        <TreeNode key={c.id} item={c} depth={depth + 1} selectedId={selectedId} onSelect={onSelect} />
      ))}
    </>
  );
}

function VerdictChip({ verdict, score }: { verdict: string | null; score: number | null }) {
  if (!verdict) return <Chip size="small" label="проверяется" />;
  const color = verdict === 'Accepted' ? 'success' : verdict === 'Wrong Answer' ? 'error' : 'warning';
  return <Chip size="small" color={color} label={score !== null ? `${verdict} · ${score}` : verdict} />;
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
  const [problem, setProblem] = useState<ProblemForStudent | null>(null);
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
    setProblem(null);
    // Иначе в редакторе оставался код предыдущей задачи — ниже, после
    // загрузки problem, подставляется черновик/шаблон именно этой задачи.
    setCode('');
    setStdin('');
    api.setLastPosition(Number(courseId), item.id).catch(() => {});
    if (item.type === 'task' && item.problem_revision_id) {
      api.mySubmissions(item.problem_revision_id).then(setHistory).catch(() => {});
      api.getProblem(item.problem_revision_id).then((p) => {
        setProblem(p);
        setCode(p.draft_code ?? p.template_code ?? '');
      }).catch((e) => setError(e.message));
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
    <Layout>
      <Box sx={{ display: 'flex' }}>
        <Drawer
          variant="permanent"
          sx={{
            width: DRAWER_WIDTH, flexShrink: 0,
            '& .MuiDrawer-paper': { width: DRAWER_WIDTH, position: 'sticky', top: 64, height: 'calc(100vh - 64px)' },
          }}
        >
          <Typography variant="subtitle2" sx={{ px: 2, pt: 2, pb: 1, color: 'text.secondary' }}>
            Курс #{courseId}
          </Typography>
          <List dense>
            {tree.map((item) => (
              <TreeNode key={item.id} item={item} depth={0} selectedId={selected?.id ?? null} onSelect={selectItem} />
            ))}
          </List>
        </Drawer>

        <Box sx={{ flex: 1, minWidth: 0 }}>
          {selected && selected.type === 'snap_task' ? (
            <SnapTaskView item={selected} />
          ) : selected && selected.type === 'quiz' ? (
            <QuizView key={selected.id} item={selected} />
          ) : (
          <Container maxWidth="md" sx={{ py: 4 }}>
            {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
            {!selected && <Typography color="text.secondary">Выберите элемент курса слева.</Typography>}

            {selected && selected.type !== 'task' && (
              <Box>
                <Typography variant="h2" sx={{ mb: 2 }}>{selected.title}</Typography>
                <Box className="preview" dangerouslySetInnerHTML={{ __html: renderContentHtml(selected.content || selected.description || '') }} />
              </Box>
            )}

            {selected && selected.type === 'task' && (
              <Box>
                <Typography variant="h2" sx={{ mb: 2 }}>{selected.title}</Typography>

                {problem && (
                  <Box sx={{ mb: 2.5 }}>
                    <Box className="preview" dangerouslySetInnerHTML={{ __html: renderContentHtml(problem.statement) }} />
                    {(problem.input_format || problem.output_format) && (
                      <Stack direction="row" spacing={3} sx={{ mt: 1.5 }}>
                        {problem.input_format && (
                          <Box>
                            <Typography variant="subtitle2">Формат ввода</Typography>
                            <Typography variant="body2" color="text.secondary">{problem.input_format}</Typography>
                          </Box>
                        )}
                        {problem.output_format && (
                          <Box>
                            <Typography variant="subtitle2">Формат вывода</Typography>
                            <Typography variant="body2" color="text.secondary">{problem.output_format}</Typography>
                          </Box>
                        )}
                      </Stack>
                    )}
                    {problem.visible_tests.length > 0 && (
                      <Box sx={{ mt: 1.5 }}>
                        <Typography variant="subtitle2" sx={{ mb: 1 }}>Примеры</Typography>
                        <Stack spacing={1}>
                          {problem.visible_tests.map((t, i) => (
                            <Stack key={i} direction="row" spacing={2}>
                              <Box component="pre" sx={{ flex: 1, m: 0, fontFamily: FONT_CODE, fontSize: '0.8125rem', bgcolor: 'background.paper', border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 1.5, whiteSpace: 'pre-wrap' }}>{t.input}</Box>
                              <Box component="pre" sx={{ flex: 1, m: 0, fontFamily: FONT_CODE, fontSize: '0.8125rem', bgcolor: 'background.paper', border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 1.5, whiteSpace: 'pre-wrap' }}>{t.expected}</Box>
                            </Stack>
                          ))}
                        </Stack>
                      </Box>
                    )}
                  </Box>
                )}

                <TextField
                  multiline fullWidth minRows={12} maxRows={24}
                  value={code} onChange={(e) => setCode(e.target.value)}
                  inputProps={{ style: { fontFamily: FONT_CODE, fontSize: '0.875rem' } }}
                  sx={{ mb: 1.5, '& .MuiOutlinedInput-root': { bgcolor: 'background.paper' } }}
                />
                <TextField
                  label="stdin для «Запустить»" fullWidth size="small" value={stdin}
                  onChange={(e) => setStdin(e.target.value)}
                  sx={{ mb: 2 }}
                />

                <Stack direction="row" spacing={1.5} sx={{ mb: 2 }}>
                  <Button variant="outlined" onClick={run}>Запустить</Button>
                  <Button variant="contained" onClick={submit}>Отправить</Button>
                </Stack>

                {runResult && (
                  <Box component="pre" sx={{
                    fontFamily: FONT_CODE, fontSize: '0.8125rem', bgcolor: 'background.paper',
                    border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 1.5, whiteSpace: 'pre-wrap', mb: 2,
                  }}>
                    stdout: {runResult.stdout}
                    {'\n'}stderr: {runResult.stderr}
                    {runResult.timed_out ? '\n(превышено время выполнения)' : ''}
                  </Box>
                )}

                {submission && (
                  <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 2 }}>
                    <Typography variant="body2" color="text.secondary">Статус: {submission.status}</Typography>
                    {!TERMINAL_STATUSES.has(submission.status)
                      ? <Chip size="small" label="проверяется…" />
                      : <VerdictChip verdict={submission.verdict} score={submission.score} />}
                  </Stack>
                )}

                {history.length > 0 && (
                  <Box sx={{ mt: 3 }}>
                    <Typography variant="h3" sx={{ mb: 1.5 }}>История попыток</Typography>
                    <Stack spacing={1}>
                      {history.map((s) => (
                        <Box key={s.id} sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 1.5 }}>
                          <Stack direction="row" justifyContent="space-between" alignItems="center">
                            <Typography variant="body2" color="text.secondary">
                              {new Date(s.created_at).toLocaleString('ru-RU')}
                            </Typography>
                            <VerdictChip verdict={s.verdict} score={s.score} />
                          </Stack>
                          {s.manual_comment && (
                            <>
                              <Divider sx={{ my: 1 }} />
                              <Typography variant="body2" color="text.secondary">Комментарий: {s.manual_comment}</Typography>
                            </>
                          )}
                        </Box>
                      ))}
                    </Stack>
                  </Box>
                )}
              </Box>
            )}
          </Container>
          )}
        </Box>
      </Box>
    </Layout>
  );
}
