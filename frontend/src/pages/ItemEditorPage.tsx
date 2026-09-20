import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { api, LearningItem } from '../api';

const AUTOSAVE_INTERVAL_MS = 15_000; // EDT-006: не реже раза в 15 секунд

/** Раздел 5.3 ТЗ (EDT-*), в объёме этого MVP: Markdown вместо полноценного
 * WYSIWYG (заголовки/списки/цитаты/таблицы/ссылки/код — обычный синтаксис
 * Markdown, EDT-001 частично), вставка изображений через буфер обмена и
 * drag-drop с загрузкой на сервер (EDT-002), автосохранение (EDT-006),
 * предпросмотр как ученик переключением вкладки (EDT-007).
 *
 * Не реализовано: точная настройка alt/подписи/размера изображения (EDT-003),
 * видео через embed-ссылки с allowlist доменов (EDT-004), подсветка
 * синтаксиса кода и рендер LaTeX-формул в предпросмотре (EDT-005) —
 * см. README. */
export default function ItemEditorPage() {
  const { itemId } = useParams();
  const [item, setItem] = useState<LearningItem | null>(null);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [mode, setMode] = useState<'edit' | 'preview'>('edit');
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [uploadError, setUploadError] = useState('');
  const [loadError, setLoadError] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const dirtyRef = useRef(false);

  useEffect(() => {
    api.getItem(Number(itemId)).then((i) => {
      setItem(i);
      setTitle(i.title);
      setContent(i.content || '');
    }).catch((e: any) => setLoadError(e.message || 'Не удалось загрузить элемент'));
  }, [itemId]);

  const save = useCallback(async () => {
    if (!item || !dirtyRef.current) return;
    setStatus('saving');
    try {
      await api.updateItem(item.id, { title, content });
      dirtyRef.current = false;
      setStatus('saved');
    } catch {
      setStatus('error');
    }
  }, [item, title, content]);

  // EDT-006: автосохранение по таймеру и при уходе со страницы/потере фокуса поля.
  useEffect(() => {
    const timer = setInterval(save, AUTOSAVE_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [save]);

  const markDirty = () => {
    dirtyRef.current = true;
    setStatus('idle');
  };

  const insertAtCursor = (text: string) => {
    const el = textareaRef.current;
    if (!el) {
      setContent((c) => c + text);
      return;
    }
    const start = el.selectionStart;
    const end = el.selectionEnd;
    setContent((c) => c.slice(0, start) + text + c.slice(end));
    markDirty();
    requestAnimationFrame(() => {
      el.focus();
      el.selectionStart = el.selectionEnd = start + text.length;
    });
  };

  const uploadAndInsert = async (file: File) => {
    setUploadError('');
    try {
      const result = await api.upload(file);
      const isImage = result.content_type.startsWith('image/');
      insertAtCursor(isImage ? `![${file.name}](${result.url})\n` : `[${file.name}](${result.url})\n`);
    } catch (e: any) {
      setUploadError(e.message);
    }
  };

  // EDT-002: вставка изображения из буфера обмена (Ctrl+V).
  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const fileItem = Array.from(e.clipboardData.items).find((i) => i.kind === 'file');
    const file = fileItem?.getAsFile();
    if (file) {
      e.preventDefault();
      uploadAndInsert(file);
    }
  };

  // EDT-002: вставка файла перетаскиванием.
  const handleDrop = (e: React.DragEvent<HTMLTextAreaElement>) => {
    const file = e.dataTransfer.files[0];
    if (file) {
      e.preventDefault();
      uploadAndInsert(file);
    }
  };

  const handleFilePick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) uploadAndInsert(file);
    e.target.value = '';
  };

  if (loadError) return <div className="page error">{loadError}</div>;
  if (!item) return <div className="page">Загрузка…</div>;

  return (
    <div className="page">
      <h1>Редактирование элемента #{item.id}</h1>
      <label>
        Заголовок:
        <input value={title} onChange={(e) => { setTitle(e.target.value); markDirty(); }} onBlur={save} />
      </label>

      <div className="actions">
        <button onClick={() => setMode('edit')} disabled={mode === 'edit'}>Редактировать</button>
        {/* EDT-007: методист смотрит материал в режиме ученика до публикации. */}
        <button onClick={() => setMode('preview')} disabled={mode === 'preview'}>Предпросмотр как ученик</button>
        <label className="file-pick">
          Вставить файл
          <input type="file" onChange={handleFilePick} style={{ display: 'none' }} />
        </label>
      </div>

      {mode === 'edit' ? (
        <textarea
          ref={textareaRef}
          className="code"
          rows={18}
          value={content}
          onChange={(e) => { setContent(e.target.value); markDirty(); }}
          onBlur={save}
          onPaste={handlePaste}
          onDrop={handleDrop}
          onDragOver={(e) => e.preventDefault()}
          placeholder="Markdown: # заголовок, **жирный**, - список, ```код```, вставьте изображение через Ctrl+V или перетащите файл"
        />
      ) : (
        // SEC-006/SEC-007: marked пропускает сырой HTML из исходного текста как есть —
        // без санации методист (случайно или намеренно) мог бы вставить <script>,
        // который потом выполнится в браузере ученика.
        <div className="preview" dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(marked.parse(content) as string) }} />
      )}

      {uploadError && <p className="error">{uploadError}</p>}
      <p className="status">
        {status === 'saving' && 'сохраняется…'}
        {status === 'saved' && 'сохранено'}
        {status === 'error' && 'ошибка сохранения'}
      </p>
    </div>
  );
}
