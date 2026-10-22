import { CheckCircle, CloseFullscreen, ContentCopy, ExpandLess, ExpandMore, FolderOutlined, Lock, OpenInFull, RadioButtonUnchecked } from '@mui/icons-material';
import {
  Alert, Box, Button, Checkbox, Chip, Container, Divider, Drawer, FormControlLabel,
  FormGroup, IconButton, List, ListItem, ListItemButton, ListItemIcon, ListItemText, Paper, Stack, TextField, Tooltip, Typography,
} from '@mui/material';
import { SyntheticEvent, useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { api, LearningItemTree, ProblemForStudent, ProjectSubmission, QuizAttempt, RunResult, Submission } from '../api';
import CodeEditor from '../components/CodeEditor';
import Layout from '../components/Layout';
import { FONT_CODE } from '../theme';
import { clearLocalDraft, resolveInitialCode, writeLocalDraft } from '../utils/draftStorage';
import { renderContentHtml } from '../utils/renderContent';

const DRAFT_SAVE_DEBOUNCE_MS = 1200;

type SaveStatus = 'idle' | 'unsaved' | 'saving' | 'saved' | 'error';

const SAVE_STATUS_LABEL: Record<SaveStatus, string> = {
  idle: '',
  unsaved: 'Есть несохранённые изменения…',
  saving: 'Сохранение…',
  saved: 'Черновик сохранён',
  error: 'Не удалось сохранить черновик — проверьте соединение',
};

const POLL_INTERVAL_MS = 1000;
const TERMINAL_STATUSES = new Set(['done', 'cancelled', 'system_error']);
const DRAWER_WIDTH = 300;

const TYPE_LABEL: Record<string, string> = {
  theory: 'Теория', video: 'Видео', file: 'Файл', link: 'Ссылка',
  quiz: 'Тест', task: 'Задача', manual: 'Ручное задание', checkpoint: 'Контрольная точка',
  snap_task: 'Задание Snap!', gdevelop_task: 'Задание GDevelop', turtle_task: 'Задание Черепашка', project: 'Проект',
};

// Материалы без собственного действия завершения (в отличие от theory,
// у которой уже есть "Дальше") — должны получить кнопку "Отметить
// изученным", иначе индикатор в дереве для них никогда не загорится
// (backend/app/services/course_admin.py::mark_content_item_completed
// обрабатывает их тип, но раньше фронт никогда не звал этот эндпоинт).
const MATERIAL_COMPLETE_TYPES = new Set(['video', 'file', 'link', 'manual', 'checkpoint']);

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

const RESULT_PRE_SX = {
  fontFamily: FONT_CODE, fontSize: '0.8125rem', bgcolor: 'background.paper',
  border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 1.5, whiteSpace: 'pre-wrap' as const,
};

// Условие задачи нельзя выделить/скопировать обычным способом (ПКМ,
// Ctrl+C) — методист просил не давать ученикам вставлять условие в
// сторонние инструменты (п.14.10.2026). Это лёгкий сдерживающий барьер, не
// защита: тот, кто откроет DevTools или посмотрит исходный код страницы,
// текст всё равно получит — целенаправленно не усложняем этим IDE-редактор
// кода и поле stdin, их копировать можно как обычно.
const NO_COPY_SX = {
  userSelect: 'none' as const,
  WebkitUserSelect: 'none' as const,
};
function blockCopy(e: SyntheticEvent) {
  e.preventDefault();
}

/** Вывод ученика/требуемый вывод с одного и того же первого несовпавшего
 * теста + сырая трассировка + готовое объяснение ошибки на русском (не
 * заменяет трассировку, а дополняет, см. backend/app/services/error_explain.py).
 * Ничего не рендерит, если посылке нечего показать (например, Accepted). */
function SubmissionResultDetails({ s }: { s: Submission }) {
  const hasDiff = s.actual_output != null || s.expected_output != null;
  if (!hasDiff && !s.stderr && !s.error_explanation) return null;
  return (
    <Box sx={{ mt: 1 }}>
      {hasDiff && (
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ mb: 1.5 }}>
          <Box sx={{ flex: 1 }}>
            <Typography variant="caption" color="text.secondary">Ваш вывод</Typography>
            <Box component="pre" sx={RESULT_PRE_SX}>{s.actual_output ?? s.stdout}</Box>
          </Box>
          <Box sx={{ flex: 1 }}>
            <Typography variant="caption" color="text.secondary">Должно быть</Typography>
            <Box component="pre" sx={RESULT_PRE_SX}>{s.expected_output}</Box>
          </Box>
        </Stack>
      )}
      {s.stderr && (
        <Box component="pre" sx={{ ...RESULT_PRE_SX, mb: s.error_explanation ? 1 : 0 }}>{s.stderr}</Box>
      )}
      {s.error_explanation && <Alert severity="info">{s.error_explanation}</Alert>}
    </Box>
  );
}

/** Ученик прикрепляет файлы к проекту (произвольный код и т.п.), отправляет
 * на проверку тренеру; "на доработку" не редактирует старую попытку — донос
 * нового файла заводит следующую (см. app/services/project_admin.py в
 * Codelab), поэтому после каждой загрузки состояние перечитывается целиком. */
function ProjectView({ item }: { item: LearningItemTree }) {
  const [submission, setSubmission] = useState<ProjectSubmission | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const load = async () => {
    try {
      setSubmission(await api.getProjectSubmission(item.id));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setError('');
    setSubmission(null);
    void load();
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
    } catch (e: any) {
      setError(e.message);
    } finally {
      // Перечитываем состояние сервера даже при ошибке посередине —
      // файлы, которые успели загрузиться до отказавшего, должны появиться
      // в списке, а не выглядеть как "ничего не загрузилось".
      await load();
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

  if (loading) {
    return <Typography color="text.secondary">Загрузка файлов…</Typography>;
  }
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
const TURTLE_URL = 'https://turtle.tirskix.space';

/** Слева — пошаговая инструкция (стрелки листают steps), справа — статичный
 * iframe редактора (Snap!/GDevelop/Черепашка). iframe рендерится безусловно
 * на каждый рендер компонента, поэтому не перемонтируется при листании шагов
 * или переключении полноэкранного режима — сохраняется состояние проекта
 * ученика внутри редактора (у Черепашки — ещё и в localStorage самого
 * редактора, см. turtle.tirskix.space). Общий для snap_task, gdevelop_task и
 * turtle_task — все устроены одинаково, различаются только адресом редактора
 * и подписями. */
const DEFAULT_PANE_PERCENT = 42;
const MIN_PANE_PERCENT = 15;
const MAX_PANE_PERCENT = 85;

function StepIframeTaskView({ item, iframeUrl, iframeTitle, expandLabel, courseId, onCompleted }: {
  item: LearningItemTree; iframeUrl: string; iframeTitle: string; expandLabel: string;
  courseId: number; onCompleted: () => void;
}) {
  const steps = item.steps || [];
  const [stepIndex, setStepIndex] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const [marking, setMarking] = useState(false);
  // Ширина левой панели (инструкция) в процентах — ученик тянет разделитель,
  // чтобы расширить редактор (Snap!/GDevelop/Черепашка) вправо или влево за
  // пределы исходных 42%. На мобильной раскладке (xs, панели друг под
  // другом) ширина не применяется — там работает брейкпоинт из sx.
  const [panePercent, setPanePercent] = useState(DEFAULT_PANE_PERCENT);
  const [isDragging, setIsDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => { setStepIndex(0); }, [item.id]);

  useEffect(() => {
    if (!isDragging) return;
    const onMove = (e: MouseEvent) => {
      if (!containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const percent = ((e.clientX - rect.left) / rect.width) * 100;
      setPanePercent(Math.min(MAX_PANE_PERCENT, Math.max(MIN_PANE_PERCENT, percent)));
    };
    const onUp = () => setIsDragging(false);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [isDragging]);

  const step = steps[stepIndex];

  return (
    <Box ref={containerRef} sx={{ display: 'flex', height: 'calc(100vh - 64px)', width: '100%' }}>
      <Box
        sx={{
          // Без брейкпоинта sm инструкция растягивалась на 100% ширины уже
          // при <900px (MUI берёт xs-значение, пока не встретит явный
          // sm/md) — редактор/панель Skulpt справа сжималась в 0 (совсем
          // не видна) на любом окне уже, чем "десктоп" в привычном смысле.
          width: expanded ? 0 : { xs: '100%', sm: `${panePercent}%` },
          minWidth: expanded ? 0 : { sm: 0 },
          overflow: 'hidden',
          transition: isDragging ? 'none' : 'width 0.2s ease',
          borderRight: expanded ? 'none' : '1px solid',
          borderColor: 'divider',
          display: 'flex',
          flexDirection: 'column',
          flexShrink: 0,
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
        {/* Snap!/GDevelop/Черепашка пока без автопроверки (README) — это
            единственный способ для ученика получить зелёную отметку. */}
        <Stack direction="row" sx={{ p: 2, borderTop: '1px solid', borderColor: 'divider' }}>
          <Button
            variant={item.completed ? 'outlined' : 'contained'}
            color="success"
            disabled={item.completed || marking}
            startIcon={item.completed ? <CheckCircle fontSize="small" /> : undefined}
            onClick={async () => {
              setMarking(true);
              try {
                await api.completeItem(courseId, item.id);
                onCompleted();
              } finally {
                setMarking(false);
              }
            }}
          >
            {item.completed ? 'Выполнено' : 'Отметить выполненным'}
          </Button>
        </Stack>
      </Box>

      {!expanded && (
        <Box
          onMouseDown={() => setIsDragging(true)}
          sx={{
            display: { xs: 'none', sm: 'block' },
            width: 6,
            flexShrink: 0,
            cursor: 'col-resize',
            bgcolor: isDragging ? 'primary.main' : 'divider',
            '&:hover': { bgcolor: 'primary.main' },
          }}
        />
      )}

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
        <Box sx={{ flex: 1, position: 'relative' }}>
          <iframe
            src={iframeUrl}
            title={iframeTitle}
            style={{ width: '100%', height: '100%', border: 'none', display: 'block' }}
          />
          {isDragging && (
            <Box sx={{ position: 'absolute', inset: 0, cursor: 'col-resize' }} />
          )}
        </Box>
      </Box>
    </Box>
  );
}

/** Проект с редактором "Черепашка" (type=project, embed_editor="turtle"):
 * тот же iframe, что у turtle_task, но вместо самоотметки — кнопка "Сдать
 * проект" внутри самого редактора шлёт код родителю через postMessage
 * ({type:'codelab-turtle-submit', taskId, code}); мы прикрепляем его файлом
 * к ProjectSubmission и сразу отправляем на проверку тренеру (как
 * ProjectView, только без формы ручной загрузки — файл приходит из
 * редактора). Проверяем event.origin/taskId, чтобы не принять сообщение
 * от постороннего фрейма или от другого задания "Черепашка" на той же
 * странице. */
function TurtleProjectView({ item }: { item: LearningItemTree }) {
  const [submission, setSubmission] = useState<ProjectSubmission | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    try {
      setSubmission(await api.getProjectSubmission(item.id));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [item.id]);

  useEffect(() => {
    setError('');
    setSubmission(null);
    setLoading(true);
    void load();
  }, [item.id, load]);

  useEffect(() => {
    const turtleOrigin = new URL(TURTLE_URL).origin;
    const onMessage = async (event: MessageEvent) => {
      if (event.origin !== turtleOrigin) return;
      const data = event.data as { type?: string; taskId?: number; code?: string } | null;
      if (!data || data.type !== 'codelab-turtle-submit' || data.taskId !== item.id) return;
      const source = event.source as Window | null;
      const reply = (ok: boolean, message: string) => {
        source?.postMessage({ type: 'codelab-turtle-submit-result', taskId: item.id, ok, message }, turtleOrigin);
      };
      const code = typeof data.code === 'string' ? data.code : '';
      if (!code.trim()) {
        reply(false, 'Пустой проект — нечего сдавать.');
        return;
      }
      setSubmitting(true);
      setError('');
      try {
        const file = new File([code], `turtle_project_${item.id}.py`, { type: 'text/x-python' });
        await api.uploadProjectFile(item.id, file);
        const fresh = await api.getProjectSubmission(item.id);
        const submitted = await api.submitProjectSubmission(fresh.id);
        setSubmission(submitted);
        reply(true, 'Проект отправлен на проверку тренеру.');
      } catch (e: any) {
        setError(e.message);
        reply(false, e.message || 'Не удалось отправить проект.');
      } finally {
        setSubmitting(false);
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [item.id]);

  const lastFile = submission && submission.files.length > 0 ? submission.files[submission.files.length - 1] : null;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 64px)', width: '100%' }}>
      <Box sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
        <Typography variant="h2" sx={{ mb: 1 }}>{item.title}</Typography>
        {(item.content || item.description) && (
          <Box className="preview" sx={{ mb: 1.5 }} dangerouslySetInnerHTML={{ __html: renderContentHtml(item.content || item.description || '') }} />
        )}
        {!loading && (
          <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" sx={{ rowGap: 1 }}>
            {submission && (
              <Chip size="small" color={PROJECT_STATUS_COLOR[submission.status]} label={PROJECT_STATUS_LABEL[submission.status] || submission.status} />
            )}
            {submission?.due_at && (
              <Chip
                size="small"
                color={submission.is_overdue ? 'error' : 'default'}
                label={`Срок сдачи: ${formatDateTime(submission.due_at)}${submission.is_overdue ? ' — просрочено' : ''}`}
              />
            )}
            {submission && submission.attempt_number > 1 && <Chip size="small" label={`Попытка ${submission.attempt_number}`} />}
            {submitting && <Chip size="small" color="info" label="Отправляем…" />}
          </Stack>
        )}
        {error && <Alert severity="error" sx={{ mt: 1.5 }}>{error}</Alert>}
        {submission?.status === 'needs_revision' && (
          <Alert severity="warning" sx={{ mt: 1.5 }}>
            Тренер вернул работу на доработку. Нажмите «Сдать проект» в редакторе ещё раз — это создаст новую попытку.
          </Alert>
        )}
        {submission && submission.status !== 'draft' && submission.review_comment && (
          <Box sx={{ mt: 1.5 }}>
            <Typography variant="subtitle2">Комментарий тренера</Typography>
            <Typography variant="body2" color="text.secondary">{submission.review_comment}</Typography>
            {submission.score !== null && <Typography variant="body2" color="text.secondary">Оценка: {submission.score}</Typography>}
          </Box>
        )}
        {lastFile && (
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
            Последняя сданная версия:{' '}
            <a href={api.projectFileDownloadUrl(lastFile.id)} target="_blank" rel="noopener">{lastFile.original_filename}</a>
            {' '}· {formatDateTime(lastFile.uploaded_at)}
          </Typography>
        )}
      </Box>
      <Box sx={{ flex: 1, position: 'relative' }}>
        <iframe
          src={`${TURTLE_URL}?task=${item.id}&blank=1&project=1`}
          title="Черепашка"
          style={{ width: '100%', height: '100%', border: 'none', display: 'block' }}
        />
      </Box>
    </Box>
  );
}

/** Прохождение теста (type=quiz) — один тип вопроса, несколько правильных
 * ответов (checkbox). key={item.id} на месте использования сбрасывает
 * локальный стейт при переключении на другой тест (та же проблема, что
 * чинили для code-редактора задач — старые отметки не должны переползать
 * на новый тест). */
function QuizView({ item, onSubmitted }: { item: LearningItemTree; onSubmitted: () => void }) {
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
      // Индикатор в дереве курса (зелёный кружок) считается по 100% —
      // обновляем сразу, без перезагрузки страницы, как и после задачи.
      onSubmitted();
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
  const isStructural = ['module', 'submodule', 'topic', 'subtopic'].includes(item.type);
  // Развёрнуто по умолчанию — прежнее поведение (все узлы всегда видны),
  // стрелка только добавляет возможность свернуть, не меняет дефолт.
  const [open, setOpen] = useState(true);

  return (
    <>
      {isStructural ? (
        <ListItem
          dense
          sx={{
            pl: 1 + depth * 2,
            pr: 1,
            py: 0.35,
            my: 0.25,
            minHeight: 36,
            bgcolor: item.type === 'module' ? 'action.hover' : 'action.selected',
            borderLeft: '3px solid',
            borderColor: item.type === 'module' ? 'primary.main' : 'secondary.main',
            borderRadius: '0 8px 8px 0',
          }}
        >
          <ListItemIcon sx={{ minWidth: 28, color: item.completed ? 'success.main' : 'text.secondary' }}>
            {item.completed ? <CheckCircle fontSize="small" /> : <FolderOutlined fontSize="small" />}
          </ListItemIcon>
          <ListItemText
            primary={item.title}
            secondary={isStructural ? undefined : TYPE_LABEL[item.type] || item.type}
            primaryTypographyProps={{ fontSize: '0.78rem', fontWeight: 700, lineHeight: 1.2 }}
            secondaryTypographyProps={{ fontSize: '0.65rem', lineHeight: 1.1 }}
          />
          {hasChildren && (
            <ListItemIcon
              sx={{ minWidth: 24, justifyContent: 'flex-end', cursor: 'pointer' }}
              onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
            >
              {open ? <ExpandLess fontSize="small" /> : <ExpandMore fontSize="small" />}
            </ListItemIcon>
          )}
        </ListItem>
      ) : (
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
      )}
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
  const [lectureNavigationBusy, setLectureNavigationBusy] = useState(false);
  const [completingItem, setCompletingItem] = useState(false);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  // IDE-002: id пользователя — только для ключа локальной резервной копии
  // черновика (utils/draftStorage.ts), чтобы она не путалась между учениками
  // на одном браузере/компьютере. До её загрузки draftStorage использует
  // временный общий бакет — минимальный, самоисправляющийся зазор (следующее
  // успешное сохранение на сервер всё расставит по местам).
  const [meId, setMeId] = useState<number | null>(null);
  // Направления ученика (из LMS, см. kodex_sso.py на портале) — используются,
  // например, чтобы показать кнопку копирования входных данных примеров
  // только ученикам направления "эксперт" (п.14.10.2026).
  const [meDirections, setMeDirections] = useState<string[]>([]);
  useEffect(() => {
    api.me().then((me) => { setMeId(me.id); setMeDirections(me.directions || []); }).catch(() => {});
  }, []);
  const isExpertDirection = meDirections.includes('expert');

  // Текущая задача, которую видит ученик в редакторе — "источник истины" для
  // debounce-сохранения и защиты от гонки, когда ответ сервера приходит уже
  // после того, как ученик переключился на другую задачу: ссылка нужна,
  // чтобы колбэки fetch/setTimeout всегда знали АКТУАЛЬНУЮ задачу, а не ту,
  // что была на момент их запуска (замыкание на code/selected было бы
  // устаревшим).
  const activeProblemRef = useRef<number | null>(null);
  const pendingCodeRef = useRef('');
  const draftSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flushDraftSave = useCallback((problemRevisionId: number, codeToSave: string) => {
    if (draftSaveTimer.current) {
      clearTimeout(draftSaveTimer.current);
      draftSaveTimer.current = null;
    }
    setSaveStatus('saving');
    api.saveDraft(problemRevisionId, codeToSave)
      .then(() => {
        // Пока шёл запрос, ученик мог уже уйти на другую задачу — не
        // показываем "сохранено" по чужому для текущего экрана результату.
        if (activeProblemRef.current !== problemRevisionId) return;
        clearLocalDraft(meId, problemRevisionId); // сервер принял — локальная резервная копия больше не нужна
        setSaveStatus('saved');
      })
      .catch(() => {
        if (activeProblemRef.current !== problemRevisionId) return;
        setSaveStatus('error');
      });
  }, [meId]);

  // Debounce ещё не успел сработать, а вкладка уже закрывается/обновляется —
  // отправляем последний известный код синхронно (keepalive переживает уход
  // со страницы, обычный fetch-промис — нет). Та же функция вызывается и при
  // размонтировании компонента (уход со страницы курса целиком).
  const flushOnLeave = useCallback(() => {
    if (!draftSaveTimer.current || !activeProblemRef.current) return;
    clearTimeout(draftSaveTimer.current);
    draftSaveTimer.current = null;
    try {
      fetch('/api/submissions/draft', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        keepalive: true,
        body: JSON.stringify({ problem_revision_id: activeProblemRef.current, code: pendingCodeRef.current }),
      });
    } catch {
      // Уже есть localStorage-снимок на каждое изменение (handleCodeChange) — он переживёт закрытие вкладки и без этого запроса.
    }
  }, []);

  useEffect(() => {
    window.addEventListener('beforeunload', flushOnLeave);
    return () => {
      window.removeEventListener('beforeunload', flushOnLeave);
      flushOnLeave();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  const handleCodeChange = (value: string) => {
    setCode(value);
    pendingCodeRef.current = value;
    const problemRevisionId = activeProblemRef.current;
    if (!problemRevisionId) return;
    // Мгновенный локальный снимок — страховка на случай быстрого ухода или
    // ошибки сети, ПЕРЕД debounce-запросом на сервер, не вместо него.
    writeLocalDraft(meId, problemRevisionId, value);
    setSaveStatus('unsaved');
    if (draftSaveTimer.current) clearTimeout(draftSaveTimer.current);
    draftSaveTimer.current = setTimeout(() => flushDraftSave(problemRevisionId, value), DRAFT_SAVE_DEBOUNCE_MS);
  };

  const selectItem = (item: LearningItemTree) => {
    // Не ждём debounce — последние несколько секунд набора на ПРЕДЫДУЩЕЙ
    // задаче должны уйти на сервер до переключения, а не потеряться.
    flushOnLeave();

    setSelected(item);
    setRunResult(null);
    setSubmission(null);
    setHistory([]);
    setProblem(null);
    // Иначе в редакторе оставался код предыдущей задачи — ниже, после
    // загрузки problem, подставляется черновик/шаблон именно этой задачи.
    setCode('');
    setStdin('');
    setSaveStatus('idle');
    pendingCodeRef.current = '';
    activeProblemRef.current = item.type === 'task' ? item.problem_revision_id ?? null : null;
    api.setLastPosition(Number(courseId), item.id)
      .then(() => api.getTree(Number(courseId)).then(setTree))
      .catch(() => {});
    if (item.type === 'task' && item.problem_revision_id) {
      const problemRevisionId = item.problem_revision_id;
      api.mySubmissions(problemRevisionId).then((h) => {
        // Та же гонка, что и с getProblem ниже: если ученик уже переключился
        // на другую задачу, пока шёл запрос, — не подставляем сюда историю
        // уже неактуальной (предыдущей) задачи.
        if (activeProblemRef.current !== problemRevisionId) return;
        setHistory(h);
      }).catch(() => {});
      api.getProblem(problemRevisionId).then((p) => {
        // Пока грузилась задача, ученик уже мог уйти на другую — не
        // подставляем её код/статус в уже неактуальный экран.
        if (activeProblemRef.current !== problemRevisionId) return;
        setProblem(p);
        const { code: initialCode, shouldPushToServer, source } = resolveInitialCode({
          userId: meId,
          problemRevisionId,
          serverDraftCode: p.draft_code,
          serverDraftUpdatedAt: p.draft_updated_at,
          templateCode: p.template_code,
        });
        setCode(initialCode);
        pendingCodeRef.current = initialCode;
        if (shouldPushToServer) {
          // Локальная резервная копия была новее серверного черновика —
          // досылаем её, чтобы сервер и другие вкладки/устройства её тоже увидели.
          flushDraftSave(problemRevisionId, initialCode);
        } else {
          // source==='template' — это ещё не черновик, а стартовая заготовка:
          // ничего не сохранено, статус "Черновик сохранён" был бы неправдой.
          setSaveStatus(source === 'server' ? 'saved' : 'idle');
        }
      }).catch((e) => setError(e.message));
    }
  };

  const refreshTreeAndSelected = () => {
    api.getTree(Number(courseId)).then((t) => {
      setTree(t);
      if (selected) {
        const refreshed = flatten(t).find((i) => i.id === selected.id);
        if (refreshed) setSelected(refreshed);
      }
    }).catch(() => {});
  };

  const markSelectedCompleted = async () => {
    if (!selected) return;
    setCompletingItem(true);
    try {
      await api.completeItem(Number(courseId), selected.id);
      refreshTreeAndSelected();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setCompletingItem(false);
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
              const prid = selected.problem_revision_id;
              api.mySubmissions(prid).then((h) => {
                if (activeProblemRef.current !== prid) return;
                setHistory(h);
              }).catch(() => {});
            }
            // Индикатор в дереве курса (зелёный кружок у задачи, и у
            // родительских разделов, если это была последняя обязательная
            // задача) — обновляем сразу, без перезагрузки страницы.
            refreshTreeAndSelected();
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

  const navigationItems = flatten(tree).filter((item) =>
    item.unlocked && !['module', 'submodule', 'topic', 'subtopic'].includes(item.type),
  );
  const lectureIndex = selected?.type === 'theory'
    ? navigationItems.findIndex((item) => item.id === selected.id)
    : -1;
  const previousLecture = lectureIndex > 0 ? navigationItems[lectureIndex - 1] : null;
  const nextLecture = lectureIndex >= 0 && lectureIndex < navigationItems.length - 1
    ? navigationItems[lectureIndex + 1]
    : null;

  const moveLecture = async (target: LearningItemTree, completeCurrent: boolean) => {
    if (!selected || lectureNavigationBusy) return;
    setLectureNavigationBusy(true);
    setError('');
    try {
      if (completeCurrent) await api.completeItem(Number(courseId), selected.id);
      await api.setLastPosition(Number(courseId), target.id);
      const refreshedTree = await api.getTree(Number(courseId));
      setTree(refreshedTree);
      const refreshedTarget = flatten(refreshedTree).find((item) => item.id === target.id) || target;
      selectItem(refreshedTarget);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLectureNavigationBusy(false);
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
          <List dense>
            {tree.map((item) => (
              <TreeNode key={item.id} item={item} depth={0} selectedId={selected?.id ?? null} onSelect={selectItem} />
            ))}
          </List>
        </Drawer>

        <Box sx={{ flex: 1, minWidth: 0 }}>
          {selected && selected.type === 'snap_task' ? (
            <StepIframeTaskView item={selected} iframeUrl={SNAP_URL} iframeTitle="Snap!" expandLabel="Snap! на весь экран" courseId={Number(courseId)} onCompleted={refreshTreeAndSelected} />
          ) : selected && selected.type === 'gdevelop_task' ? (
            <StepIframeTaskView item={selected} iframeUrl={GDEVELOP_URL} iframeTitle="GDevelop" expandLabel="GDevelop на весь экран" courseId={Number(courseId)} onCompleted={refreshTreeAndSelected} />
          ) : selected && selected.type === 'turtle_task' ? (
            <StepIframeTaskView
              item={selected}
              // ?task=<id> — черепашка хранит код/рисунок ученика в своём
              // localStorage по этому ключу, чтобы разные задания "Черепашка"
              // в разных уроках не делили один и тот же сохранённый прогресс.
              iframeUrl={`${TURTLE_URL}?task=${selected.id}&blank=1`}
              iframeTitle="Черепашка"
              expandLabel="Черепашка на весь экран"
              courseId={Number(courseId)}
              onCompleted={refreshTreeAndSelected}
            />
          ) : selected && selected.type === 'project' && selected.embed_editor === 'turtle' ? (
            <TurtleProjectView key={selected.id} item={selected} />
          ) : selected && selected.type === 'quiz' ? (
            <QuizView key={selected.id} item={selected} onSubmitted={refreshTreeAndSelected} />
          ) : (
          <Container maxWidth="md" sx={{ py: 4 }}>
            {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
            {!selected && <Typography color="text.secondary">Выберите элемент курса слева.</Typography>}

            {selected && selected.type !== 'task' && selected.type !== 'project' && (
              <Box>
                <Typography variant="h2" sx={{ mb: 2 }}>{selected.title}</Typography>
                <Box
                  className={`preview${selected.type === 'theory' ? ' lecture-content' : ''}`}
                  onCopy={selected.type === 'theory' ? (event) => event.preventDefault() : undefined}
                  onCut={selected.type === 'theory' ? (event) => event.preventDefault() : undefined}
                  onContextMenu={selected.type === 'theory' ? (event) => event.preventDefault() : undefined}
                  dangerouslySetInnerHTML={{ __html: renderContentHtml(selected.content || selected.description || '') }}
                />
                {selected.type === 'theory' && (
                  <Stack direction="row" justifyContent="space-between" sx={{ mt: 4 }}>
                    <Button
                      variant="outlined"
                      disabled={!previousLecture || lectureNavigationBusy}
                      onClick={() => previousLecture && moveLecture(previousLecture, false)}
                    >
                      Назад
                    </Button>
                    <Button
                      variant="contained"
                      disabled={!nextLecture || lectureNavigationBusy}
                      onClick={() => nextLecture && moveLecture(nextLecture, true)}
                    >
                      Дальше
                    </Button>
                  </Stack>
                )}
                {/* video/file/link/manual/checkpoint — раньше нечем было
                    отметить такой материал пройденным (только у теории была
                    кнопка "Дальше"), индикатор в дереве никогда не загорался. */}
                {MATERIAL_COMPLETE_TYPES.has(selected.type) && (
                  <Stack direction="row" sx={{ mt: 4 }}>
                    <Button
                      variant={selected.completed ? 'outlined' : 'contained'}
                      color="success"
                      disabled={selected.completed || completingItem}
                      startIcon={selected.completed ? <CheckCircle fontSize="small" /> : undefined}
                      onClick={markSelectedCompleted}
                    >
                      {selected.completed ? 'Изучено' : 'Отметить изученным'}
                    </Button>
                  </Stack>
                )}
              </Box>
            )}

            {selected && selected.type === 'project' && <ProjectView item={selected} />}

            {selected && selected.type === 'task' && (
              <Box>
                <Typography variant="h2" sx={{ mb: 2 }}>{selected.title}</Typography>

                {problem && (
                  <Box sx={{ mb: 2.5, ...NO_COPY_SX }} onCopy={blockCopy} onContextMenu={blockCopy}>
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
                              <Box sx={{ position: 'relative', flex: 1 }}>
                                <Box component="pre" sx={{ m: 0, color: 'text.primary', fontFamily: FONT_CODE, fontSize: '0.8125rem', bgcolor: 'background.default', border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 1.5, pr: isExpertDirection ? 5 : 1.5, whiteSpace: 'pre-wrap' }}>{t.input}</Box>
                                {isExpertDirection && (
                                  <Tooltip title="Скопировать входные данные">
                                    <IconButton
                                      size="small"
                                      sx={{ position: 'absolute', top: 4, right: 4 }}
                                      onClick={() => { navigator.clipboard.writeText(t.input); }}
                                    >
                                      <ContentCopy fontSize="inherit" />
                                    </IconButton>
                                  </Tooltip>
                                )}
                              </Box>
                              <Box component="pre" sx={{ flex: 1, m: 0, color: 'text.primary', fontFamily: FONT_CODE, fontSize: '0.8125rem', bgcolor: 'background.paper', border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 1.5, whiteSpace: 'pre-wrap' }}>{t.expected}</Box>
                            </Stack>
                          ))}
                        </Stack>
                      </Box>
                    )}
                  </Box>
                )}

                <Box sx={{ mb: 0.5 }}>
                  <CodeEditor
                    key={selected.id}
                    value={code}
                    onChange={handleCodeChange}
                    language={problem?.language ?? 'python3'}
                  />
                </Box>
                <Typography
                  variant="caption"
                  color={saveStatus === 'error' ? 'error' : 'text.secondary'}
                  sx={{ display: 'block', minHeight: '1.2em', mb: 1 }}
                >
                  {SAVE_STATUS_LABEL[saveStatus]}
                </Typography>
                <TextField
                  label="stdin для «Запустить»" helperText="Каждое значение input() — с новой строки"
                  multiline fullWidth minRows={2} maxRows={6}
                  inputProps={{ style: { fontFamily: FONT_CODE } }}
                  value={stdin}
                  onChange={(e) => setStdin(e.target.value)}
                  sx={{ mb: 2 }}
                />

                <Stack direction="row" spacing={1.5} sx={{ mb: 2 }}>
                  <Button variant="outlined" onClick={run}>Запустить</Button>
                  <Button variant="contained" onClick={submit}>Отправить</Button>
                </Stack>

                {runResult && (
                  <Box sx={{ mb: 2 }}>
                    <Box component="pre" sx={{ ...RESULT_PRE_SX, mb: runResult.error_explanation ? 1 : 0 }}>
                      stdout: {runResult.stdout}
                      {'\n'}stderr: {runResult.stderr}
                      {runResult.timed_out ? '\n(превышено время выполнения)' : ''}
                    </Box>
                    {runResult.error_explanation && <Alert severity="info">{runResult.error_explanation}</Alert>}
                  </Box>
                )}

                {submission && (
                  <Box sx={{ mb: 2 }}>
                    <Stack direction="row" spacing={1.5} alignItems="center">
                      <Typography variant="body2" color="text.secondary">Статус: {submission.status}</Typography>
                      {!TERMINAL_STATUSES.has(submission.status)
                        ? <Chip size="small" label="проверяется…" />
                        : <VerdictChip verdict={submission.verdict} score={submission.score} />}
                    </Stack>
                    {TERMINAL_STATUSES.has(submission.status) && <SubmissionResultDetails s={submission} />}
                  </Box>
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
                          <SubmissionResultDetails s={s} />
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
