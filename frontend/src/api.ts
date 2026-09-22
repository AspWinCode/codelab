const BASE = '/api';

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Ошибка ${res.status}`);
  }
  return res.json();
}

export interface Me {
  id: number;
  external_ref: string;
  full_name: string;
  role: string;
  groups: string[];
  directions: string[];
}

export interface Course {
  id: number;
  slug: string | null;
  title: string;
  description: string | null;
  status: string;
}

export interface RunResult {
  stdout: string;
  stderr: string;
  timed_out: boolean;
}

// JDG-001: посылка проходит статусы created → queued → running → done
// (или cancelled/system_error) — воркер обрабатывает очередь асинхронно.
export interface Submission {
  id: number;
  status: 'created' | 'queued' | 'running' | 'done' | 'cancelled' | 'system_error';
  verdict: string | null;
  score: number | null;
  stdout: string | null;
  stderr: string | null;
  manual_score_override: number | null;
  manual_comment: string | null;
  created_at: string;
}

export interface SnapStep {
  title: string;
  content: string;
}

// Один тип вопроса — несколько правильных ответов (checkbox). У ученика
// `correct` всегда false (сервер стирает его перед выдачей, см. Codelab
// course_admin.build_student_tree/_strip_quiz_answers) — просто не читаем.
export interface QuizOption {
  text: string;
  correct: boolean;
}

export interface QuizQuestion {
  text: string;
  options: QuizOption[];
}

export interface QuizAttempt {
  id: number;
  item_id: number;
  score: number;
  created_at: string;
}

export interface LearningItem {
  id: number;
  type: string;
  title: string;
  description: string | null;
  content: string | null;
  parent_id: number | null;
  is_required: boolean;
  weight: number;
  position: number;
  unlock_rules: Record<string, unknown>;
  problem_revision_id: number | null;
  steps: SnapStep[] | null;
  quiz_questions: QuizQuestion[] | null;
}

export interface LearningItemTree extends LearningItem {
  children: LearningItemTree[];
  unlocked: boolean;
  completed: boolean;
}

export interface UploadResult {
  url: string;
  content_type: string;
  size: number;
}

// STU-001: главная страница ученика.
export interface NextItem {
  id: number;
  title: string;
}

export interface DashboardCourse {
  course_id: number;
  title: string;
  percent: number;
  completed_items: number;
  total_items: number;
  deadline: string | null;
  next_item: NextItem | null;
  last_item_id: number | null;
}

export interface RecentResult {
  submission_id: number;
  task_title: string;
  verdict: string | null;
  score: number | null;
  created_at: string;
}

export interface Dashboard {
  courses: DashboardCourse[];
  recent_results: RecentResult[];
}

// NTF-001/003
export interface Notification {
  id: number;
  type: string;
  title: string;
  body: string | null;
  is_read: boolean;
  created_at: string;
}

export interface NotificationPreference {
  type: string;
  enabled: boolean;
  mandatory: boolean;
}

// STU-003: условие задачи для ученика — без reference_solution и скрытых тестов.
export interface ProblemTest {
  input: string;
  expected: string;
  is_hidden: boolean;
  group: string;
  weight: number;
}

export interface ProblemForStudent {
  id: number;
  title: string;
  statement: string;
  input_format: string | null;
  output_format: string | null;
  constraints: string | null;
  time_limit_ms: number;
  memory_limit_mb: number;
  language: string;
  allowed_libraries: string[];
  visible_tests: ProblemTest[];
  template_code: string | null;
  draft_code: string | null;
}

export const api = {
  me: () => request<Me>('/auth/me'),
  courses: () => request<Course[]>('/courses'),
  dashboard: () => request<Dashboard>('/me/dashboard'),
  getTree: (courseId: number) => request<LearningItemTree[]>(`/courses/${courseId}/tree`),
  setLastPosition: (courseId: number, itemId: number) =>
    request(`/courses/${courseId}/last-position`, { method: 'PUT', body: JSON.stringify({ item_id: itemId }) }),
  getItem: (id: number) => request<LearningItem>(`/courses/items/${id}`),
  updateItem: (id: number, patch: Partial<Pick<LearningItem, 'title' | 'content' | 'description'>>) =>
    request<LearningItem>(`/courses/items/${id}`, { method: 'PUT', body: JSON.stringify(patch) }),
  mySubmissions: (problemRevisionId: number) =>
    request<Submission[]>(`/submissions?problem_revision_id=${problemRevisionId}`),
  getProblem: (problemRevisionId: number) => request<ProblemForStudent>(`/courses/problems/${problemRevisionId}`),
  submitQuizAttempt: (itemId: number, answers: number[][]) =>
    request<QuizAttempt>(`/courses/quizzes/${itemId}/attempts`, { method: 'POST', body: JSON.stringify({ answers }) }),
  myQuizAttempts: (itemId: number) => request<QuizAttempt[]>(`/courses/quizzes/${itemId}/attempts`),
  upload: async (file: File): Promise<UploadResult> => {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`${BASE}/uploads`, { method: 'POST', credentials: 'include', body: form });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Ошибка ${res.status}`);
    }
    return res.json();
  },
  run: (problem_revision_id: number, code: string, stdin: string) =>
    request<RunResult>('/submissions/run', {
      method: 'POST',
      body: JSON.stringify({ problem_revision_id, code, stdin }),
    }),
  submit: (problem_revision_id: number, code: string) =>
    request<Submission>('/submissions', {
      method: 'POST',
      body: JSON.stringify({ problem_revision_id, code }),
    }),
  getSubmission: (id: number) => request<Submission>(`/submissions/${id}`),

  notifications: (unreadOnly = false) =>
    request<Notification[]>(`/me/notifications${unreadOnly ? '?unread_only=true' : ''}`),
  markNotificationRead: (id: number) => request(`/me/notifications/${id}/read`, { method: 'PUT' }),
  notificationPreferences: () => request<NotificationPreference[]>('/me/notification-preferences'),
  updateNotificationPreference: (type: string, enabled: boolean) =>
    request(`/me/notification-preferences/${type}`, { method: 'PUT', body: JSON.stringify({ enabled }) }),
};
