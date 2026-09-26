import { CheckCircle, CloseFullscreen, ExpandLess, ExpandMore, Lock, OpenInFull, RadioButtonUnchecked } from '@mui/icons-material';
import {
  Alert, Box, Button, Checkbox, Chip, Container, Divider, Drawer, FormControlLabel,
  FormGroup, List, ListItemButton, ListItemIcon, ListItemText, Paper, Stack, TextField, Typography,
} from '@mui/material';
import { useEffect, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { api, LearningItemTree, ProblemForStudent, ProjectSubmission, QuizAttempt, RunResult, Submission } from '../api';
import Layout from '../components/Layout';
import { FONT_CODE } from '../theme';
import { renderContentHtml } from '../utils/renderContent';

const POLL_INTERVAL_MS = 1000;
const TERMINAL_STATUSES = new Set(['done', 'cancelled', 'system_error']);
const DRAWER_WIDTH = 300;

const TYPE_LABEL: Record<string, string> = {
  theory: 'Теория', video: 'Видео', file: 'Файл', link: 'Ссылка',
  quiz: 'Тест', task: 'Задача', manual: 'Ручное задание', checkpoint: 'Контрольная точка',
  snap_task: 'Задание Snap!', gdevelop_task: 'Задание GDevelop', project: 'Проект',
};

const PROJECT_STATUS_LABEL: Record<string, string> = {
  draft: 'Черновик — не отправлено', submitted: 'Отправлено, ждёт проверки',
  needs_revision: 'На доработке', accepted: 'Принято',
};

const PROJECT_STATUS_COLOR: Record<string, 'default' | 'info' | 'warning' | 'success'> = {
  draft: 'default', submitted: 'info', needs_revision: 'warning', accepted: 'success',
};

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU');
}

/** Ученик прикрепляет файлы к проекту (произвольный код и т.п.), отправляет
 * на проверку тренеру; "на доработку" не редактирует старую попытку — донос
 * нового файла заводит следующую (см. app/services/project_admin.py в
 * Codelab), поэтому после каждой загрузки состояние перечитывается целиком. */
function ProjectView({ item }: { item: LearningItemTree }) {
  const [submission, setSubmission] = useState<ProjectSubmission | null>(null);
  const [error, setError] = useState('');
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const load = () => {
    api.getProjectSubmission(item.id).then(setSubmission).catch((e) => setError(e.message));
  };

  useEffect(() => {
    setError('');
    setSubmission(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id]);

  const onFilesSelected = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);
    setError('');
    try {
      for (const file of Array.from(files)) {
        await api.uploadProjectFile(item.id, file);
      }
      load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const removeFile = async (fileId: number) => {
    setError('');
    try {
      await api.deleteProjectFile(fileId);
      load();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const submitNow = async () => {
    if (!submission) return;
    setError('');
    try {
      setSubmission(await api.submitProjectSubmission(submission.id));
    } catch (e: any) {
      setError(e.message);
    }
  };

  if (!submission) {
    return (
      <Box>
        <Typography variant="h2" sx={{ mb: 2 }}>{item.title}</Typography>
        {error && <Alert severity="error">{error}</Alert>}
      </Box>
    );
  }

  const canAttach = submission.status === 'draft' || submission.status === 'needs_revision';
  const canDelete = submission.status === 'draft';
  const canSubmit = submission.status === 'draft' && submission.files.length > 0;

  return (
    <Box>
      <Typography variant="h2" sx={{ mb: 1 }}>{item.title}</Typography>
      {(item.content || item.description) && (
        <Box className="preview" sx={{ mb: 2 }} dangerouslySetInnerHTML={{ __html: renderContentHtml(item.content || item.description || '') }} />
      )}

      <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" sx={{ mb: 2, rowGap: 1 }}>
        <Chip size="small" color={PROJECT_STATUS_COLOR[submission.status]} label={PROJECT_STATUS_LABEL[submission.status] || submission.status} />
        {submission.due_at && (
          <Chip
            size="small"
            color={submission.is_overdue ? 'error' : 'default'}
            label={`Срок сдачи: ${formatDateTime(submission.due_at)}${submission.is_overdue ? ' — просрочено' : ''}`}
          />
        )}
        {submission.attempt_number > 1 && <Chip size="small" label={`Попытка ${submission.attempt_number}`} />}
      </Stack>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {submission.status === 'needs_revision' && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Тренер вернул работу на доработку. Прикрепите исправленный файл — это создаст новую попытку.
        </Alert>
      )}

      <Typography variant="h3" sx={{ mb: 1 }}>Файлы</Typography>
      <Stack spacing={1} sx={{ mb: 2 }}>
        {submission.files.map((f) => (
          <Box key={f.id} sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 1.5 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" flexWrap="wrap">
              <Box>
                <Typography variant="body2">{f.original_filename}</Typography>
                <Typography variant="caption" color="text.secondary">
                  {(f.size / 1024).toFixed(1)} КБ · {formatDateTime(f.uploaded_at)}
                </Typography>
              </Box>
              <Stack direction="row" spacing={1}>
                <Button size="small" href={api.projectFileDownloadUrl(f.id)} target="_blank" rel="noopener">Скачать</Button>
                {canDelete && <Button size="small" color="error" onClick={() => removeFile(f.id)}>Удалить</Button>}
              </Stack>
            </Stack>
            {f.comments.length > 0 && (
              <>
                <Divider sx={{ my: 1 }} />
                <Stack spacing={0.5}>
                  {f.comments.map((c) => (
                    <Typography key={c.id} variant="body2" color="text.secondary">
                      <b>{c.author_full_name}:</b> {c.body}
                    </Typography>
                  ))}
                </Stack>
              </>
            )}
          </Box>
        ))}
        {submission.files.length === 0 && (
          <Typography variant="body2" color="text.secondary">Файлы ещё не прикреплены.</Typography>
        )}
      </Stack>

      {canAttach && (
        <Stack direction="row" spacing={1.5} sx={{ mb: 2 }}>
          <Button variant="outlined" component="label" disabled={uploading}>
            Прикрепить файл
            <input ref={fileInputRef} type="file" hidden multiple onChange={(e) => onFilesSelected(e.target.files)} />
          </Button>
          {canSubmit && <Button variant="contained" onClick={submitNow}>Отправить на проверку</Button>}
        </Stack>
      )}

      {submission.status !== 'draft' && submission.review_comment && (
        <Box sx={{ mb: 2, p: 1.5, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
          <Typography variant="subtitle2">Комментарий тренера</Typography>
          <Typography variant="body2" color="text.secondary">{submission.review_comment}</Typography>
          {submission.score !== null && (
            <Typography variant="body2" color="text.secondary">Оценка: {submission.score}</Typography>
          )}
        </Box>
      )}

      {submission.history.length > 0 && (
        <Box sx={{ mt: 3 }}>
          <Typography variant="h3" sx={{ mb: 1.5 }}>Предыдущие попытки</Typography>
          <Stack spacing={1}>
            {submission.history.map((h) => (
              <Box key={h.id} sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 1.5 }}>
                <Stack direction="row" justifyContent="space-between">
                  <Typography variant="body2">Попытка {h.attempt_number} — {PROJECT_STATUS_LABEL[h.status] || h.status}</Typography>
                  {h.score !== null && <Typography variant="body2">Оценка: {h.score}</Typography>}
                </Stack>
              </Box>
            ))}
          </Stack>
        </Box>
      )}
    </Box>
  );
}

const SNAP_URL = 'https://snap.tirskix.space';
const GDEVELOP_URL = 'https://gdevelop.tirskix.space';

/** Слева — пошаговая инструкция (стрелки листают steps), справа — статичный
 * iframe редактора (Snap!/GDevelop). iframe рендерится безусловно на каждый
 * рендер компонента, поэтому не перемонтируется при листании шагов или
 * переключении полноэкранного режима — сохраняется состояние проекта ученика
 * внутри редактора. Общий для snap_task и gdevelop_task — оба устроены
 * одинаково, различаются только адресом редактора и подписями. */
function StepIframeTaskView({ item, iframeUrl, iframeTitle, expandLabel }: {
  item: LearningItemTree; iframeUrl: string; iframeTitle: string; expandLabel: string;
}) {
  const steps = item.steps || [];
  const [stepIndex, setStepIndex] = useState(0);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => { setStepIndex(0); }, [item.id]);

  const step = steps[stepIndex];

  return (
    <Box sx={{ display: 'flex', height: 'calc(100vh - 64px)', width: '100%' }}>
      <Box
        sx={{
          width: expanded ? 0 : { xs: '100%', md: '42%' },
          minWidth: expanded ? 0 : { md: 340 },
          overflow: 'hidden',
          transition: 'width 0.2s ease',
          borderRight: expanded ? 'none' : '1px solid',
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
            startIcon={expanded ? <CloseFullscreen fontSize="small" /> : <OpenInFull fontSize="small" />}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? 'Показать инструкцию' : expandLabel}
          </Button>
        </Stack>
        <Box sx={{ flex: 1 }}>
          <iframe
            src={iframeUrl}
            title={iframeTitle}
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
            <StepIframeTaskView item={selected} iframeUrl={SNAP_URL} iframeTitle="Snap!" expandLabel="Snap! на весь экран" />
          ) : selected && selected.type === 'gdevelop_task' ? (
            <StepIframeTaskView item={selected} iframeUrl={GDEVELOP_URL} iframeTitle="GDevelop" expandLabel="GDevelop на весь экран" />
          ) : selected && selected.type === 'quiz' ? (
            <QuizView key={selected.id} item={selected} />
          ) : (
          <Container maxWidth="md" sx={{ py: 4 }}>
            {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
            {!selected && <Typography color="text.secondary">Выберите элемент курса слева.</Typography>}

            {selected && selected.type !== 'task' && selected.type !== 'project' && (
              <Box>
                <Typography variant="h2" sx={{ mb: 2 }}>{selected.title}</Typography>
                <Box className="preview" dangerouslySetInnerHTML={{ __html: renderContentHtml(selected.content || selected.description || '') }} />
              </Box>
            )}

            {selected && selected.type === 'project' && <ProjectView item={selected} />}

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
