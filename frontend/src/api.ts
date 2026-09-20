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
}

export interface UploadResult {
  url: string;
  content_type: string;
  size: number;
}

export const api = {
  me: () => request<Me>('/auth/me'),
  courses: () => request<Course[]>('/courses'),
  getItem: (id: number) => request<LearningItem>(`/courses/items/${id}`),
  updateItem: (id: number, patch: Partial<Pick<LearningItem, 'title' | 'content' | 'description'>>) =>
    request<LearningItem>(`/courses/items/${id}`, { method: 'PUT', body: JSON.stringify(patch) }),
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
};
