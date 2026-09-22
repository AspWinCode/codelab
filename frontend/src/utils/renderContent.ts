/** EDT-005 (подсветка кода + LaTeX), EDT-004 (embed-видео с allowlist доменов) —
 * общий рендер учебного контента → безопасный HTML для предпросмотра методиста
 * (ItemEditorPage) и просмотра учеником (CoursePage), чтобы не держать две
 * независимые копии этой логики.
 *
 * С 2026-09-22 основной путь авторства — rich-text редактор на портале
 * (learning-portal-main/CodelabStudioPage, TipTap), который пишет в
 * `content` уже готовый HTML, а не Markdown; видео там — настоящий
 * `<iframe>` (вставляется самим редактором после проверки домена), не
 * текстовый маркер. Старый `[[video: URL]]` и Markdown-синтаксис — наследие
 * дев-пути (Codelab ItemEditorPage, textarea) и данных, созданных до этого
 * перехода: `looksLikeHtml` решает, прогонять ли текст через marked, а
 * `[[video:]]` по-прежнему распознаётся на случай старого контента.
 *
 * Формулы ($...$ инлайн, $$...$$ блоком) и легаси-видеомаркер вынимаются
 * из исходного текста ДО парсинга и возвращаются на место ПОСЛЕ
 * DOMPurify.sanitize — так основной путь (parse → DOMPurify) остаётся
 * простым и безопасным по умолчанию (SEC-006/007), а KaTeX-разметка,
 * которую мы генерируем сами, никогда не проходит через html/markdown-парсер,
 * который мог бы её испортить.
 *
 * Настоящий `<iframe>` (из rich-text редактора) DOMPurify по умолчанию
 * вообще вырезает — ADD_TAGS открывает его обратно, а хук uponSanitizeElement
 * ниже проверяет src по тому же allowlist доменов, что и легаси-маркер:
 * доверяем не тому, что iframe пришёл "из нашего же редактора" (это можно
 * подделать прямым вызовом API), а только домену, на который он ведёт.
 */
import DOMPurify from 'dompurify';
import hljs from 'highlight.js';
import katex from 'katex';
import { Marked } from 'marked';
import { markedHighlight } from 'marked-highlight';
import { resolveVideoEmbed } from './videoEmbed';

const ALLOWED_IFRAME_HOSTS = new Set(['youtube.com', 'vk.com', 'rutube.ru']);

function isAllowedIframeSrc(src: string): boolean {
  try {
    const url = new URL(src);
    if (url.protocol !== 'https:') return false;
    return ALLOWED_IFRAME_HOSTS.has(url.hostname.replace(/^www\./, '').toLowerCase());
  } catch {
    return false;
  }
}

DOMPurify.addHook('uponSanitizeElement', (node, data) => {
  if (data.tagName !== 'iframe') return;
  const el = node as Element;
  const src = el.getAttribute('src') || '';
  if (!isAllowedIframeSrc(src)) {
    el.parentNode?.removeChild(el);
  }
});

const marked = new Marked(
  markedHighlight({
    langPrefix: 'hljs language-',
    highlight(code: string, lang: string) {
      const language = hljs.getLanguage(lang) ? lang : 'plaintext';
      return hljs.highlight(code, { language }).value;
    },
  }),
);

const PLACEHOLDER_PREFIX = 'codelabph';

interface Placeholder {
  token: string;
  html: string;
}

function makeToken(prefix: string, index: number): string {
  // Только буквы/цифры — marked/DOMPurify не имеют повода это тронуть
  // (никаких _, *, <, которые могли бы задеть Markdown-разметку вокруг).
  return `${PLACEHOLDER_PREFIX}${prefix}${index}marker`;
}

function renderMath(expr: string, displayMode: boolean): string {
  try {
    return katex.renderToString(expr, { displayMode, throwOnError: false, output: 'html' });
  } catch {
    return DOMPurify.sanitize(`<code>${expr}</code>`);
  }
}

function renderVideoOrFallback(rawUrl: string): string {
  const resolved = resolveVideoEmbed(rawUrl);
  if (!resolved) {
    return DOMPurify.sanitize(
      `<span class="video-embed-rejected">Видео не вставлено: ссылка «${rawUrl}» — не с разрешённой площадки (YouTube, VK Видео, RuTube).</span>`,
    );
  }
  // embedUrl собран нами из id, извлечённого строгим regex'ом (см. videoEmbed.ts) —
  // безопасно интерполировать напрямую, в отличие от исходной ссылки методиста.
  return (
    `<span class="video-embed">` +
    `<iframe src="${resolved.embedUrl}" loading="lazy" allowfullscreen ` +
    `sandbox="allow-scripts allow-same-origin allow-presentation" referrerpolicy="no-referrer" ` +
    `frameborder="0"></iframe></span>`
  );
}

// Грубая, но достаточная эвристика: rich-text редактор всегда пишет HTML
// (хотя бы один тег — параграф, если ничего больше), старый дев-путь и
// нетронутые методистом поля — обычный текст/Markdown без тегов вовсе.
function looksLikeHtml(text: string): boolean {
  return /<\/?[a-z][\s\S]*>/i.test(text);
}

export function renderContentHtml(content: string): string {
  const placeholders: Placeholder[] = [];

  const extract = (source: string, pattern: RegExp, toHtml: (group: string) => string): string =>
    source.replace(pattern, (_full: string, group: string) => {
      const token = makeToken('', placeholders.length);
      placeholders.push({ token, html: toHtml(group) });
      return token;
    });

  let processed = content;
  // Порядок важен: блочные формулы $$...$$ до инлайновых $...$, иначе пара
  // $$ будет ошибочно разобрана как два инлайновых маркера.
  processed = extract(processed, /\$\$([\s\S]+?)\$\$/g, (g) => renderMath(g, true));
  processed = extract(processed, /\$([^$\n]+?)\$/g, (g) => renderMath(g, false));
  // Легаси-синтаксис дев-пути (Codelab ItemEditorPage) — новый rich-text
  // редактор вставляет видео уже настоящим <iframe>, который проходит
  // через allowlist-хук DOMPurify ниже, а не через этот маркер.
  processed = extract(processed, /\[\[video:\s*(\S+?)\s*\]\]/g, (g) => renderVideoOrFallback(g));

  const rawHtml = looksLikeHtml(processed) ? processed : (marked.parse(processed, { async: false }) as string);

  // ADD_TAGS: iframe (легаси-видео и rich-text видео — оба проходят через
  // allowlist-хук выше), input (чекбоксы списка задач из rich-text редактора).
  let safeHtml = DOMPurify.sanitize(rawHtml, {
    ADD_TAGS: ['iframe', 'input'],
    ADD_ATTR: ['allow', 'allowfullscreen', 'frameborder', 'sandbox', 'referrerpolicy', 'type', 'checked', 'disabled'],
  });

  for (const { token, html } of placeholders) {
    safeHtml = safeHtml.split(token).join(html);
  }
  return safeHtml;
}
