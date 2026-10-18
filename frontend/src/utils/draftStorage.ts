// IDE-002: локальная резервная копия черновика кода — страховка на случай
// быстрого ухода со страницы (вкладка закрылась раньше, чем успел сработать
// debounce-запрос на сервер) или временной ошибки сети. Источник истины —
// всё равно сервер (Draft, backend/app/models.py); localStorage только
// закрывает зазор между последним нажатием клавиши и следующим успешным
// сохранением. Ключ включает пользователя и задачу, чтобы черновики не
// перемешивались ни между учениками на одном компьютере, ни между задачами.
const PREFIX = 'codelab:draft';

interface LocalDraft {
  code: string;
  savedAt: number;
}

function storageKey(userId: number | null, problemRevisionId: number): string {
  return `${PREFIX}:${userId ?? 'anon'}:${problemRevisionId}`;
}

export function readLocalDraft(userId: number | null, problemRevisionId: number): LocalDraft | null {
  try {
    const raw = localStorage.getItem(storageKey(userId, problemRevisionId));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (typeof parsed?.code === 'string' && typeof parsed?.savedAt === 'number') return parsed;
    return null;
  } catch {
    return null; // приватный режим/заблокированное хранилище/битый JSON — просто нет резервной копии
  }
}

export function writeLocalDraft(userId: number | null, problemRevisionId: number, code: string): void {
  try {
    localStorage.setItem(storageKey(userId, problemRevisionId), JSON.stringify({ code, savedAt: Date.now() }));
  } catch {
    // Квота/приватный режим — не критично, debounce-сохранение на сервер всё ещё работает самостоятельно.
  }
}

export function clearLocalDraft(userId: number | null, problemRevisionId: number): void {
  try {
    localStorage.removeItem(storageKey(userId, problemRevisionId));
  } catch {
    // см. writeLocalDraft
  }
}

/** Выбирает, какой код подставить при открытии задачи, и нужно ли сразу же
 * дослать его на сервер (локальная копия оказалась новее). Никогда не
 * выбирает template_code, если есть хоть какой-то черновик (локальный или
 * серверный) — иначе готовый ответ ученика подменяется стартовой заготовкой. */
export interface InitialCodeResolution {
  code: string;
  shouldPushToServer: boolean;
  // Откуда взят код — нужно отличать "это шаблон, ещё ничего не сохранено"
  // от "это уже сохранённый черновик", иначе статус-индикатор в CoursePage
  // соврёт "Черновик сохранён" для только что подставленного шаблона.
  source: 'local' | 'server' | 'template';
}

export function resolveInitialCode(params: {
  userId: number | null;
  problemRevisionId: number;
  serverDraftCode: string | null;
  serverDraftUpdatedAt: string | null;
  templateCode: string | null;
}): InitialCodeResolution {
  const local = readLocalDraft(params.userId, params.problemRevisionId);
  const serverTime = params.serverDraftUpdatedAt ? new Date(params.serverDraftUpdatedAt).getTime() : null;

  if (local && (serverTime === null || local.savedAt > serverTime)) {
    return { code: local.code, shouldPushToServer: true, source: 'local' };
  }
  if (params.serverDraftCode !== null) {
    return { code: params.serverDraftCode, shouldPushToServer: false, source: 'server' };
  }
  if (local) {
    return { code: local.code, shouldPushToServer: true, source: 'local' };
  }
  return { code: params.templateCode ?? '', shouldPushToServer: false, source: 'template' };
}
