/** EDT-005 (подсветка кода + LaTeX), EDT-004 (embed-видео с allowlist доменов) —
 * общий рендер Markdown → безопасный HTML для предпросмотра методиста
 * (ItemEditorPage) и просмотра учеником (CoursePage), чтобы не держать две
 * независимые копии этой логики.
 *
 * Формулы ($...$ инлайн, $$...$$ блоком) и видео (`[[video: URL]]`) вынимаются
 * из исходного Markdown ДО marked.parse и возвращаются на место ПОСЛЕ
 * DOMPurify.sanitize — так основной путь (marked → DOMPurify) остаётся
 * простым и безопасным по умолчанию (SEC-006/007), а KaTeX/iframe-разметка,
 * которую мы генерируем сами, никогда не проходит через марkdown-парсер,
 * который мог бы её испортить или пропустить как сырой HTML.
 */
import DOMPurify from 'dompurify';
import hljs from 'highlight.js';
import katex from 'katex';
import { Marked } from 'marked';
import { markedHighlight } from 'marked-highlight';
import { resolveVideoEmbed } from './videoEmbed';

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
  processed = extract(processed, /\[\[video:\s*(\S+?)\s*\]\]/g, (g) => renderVideoOrFallback(g));

  const rawHtml = marked.parse(processed, { async: false }) as string;
  // ADD_TAGS/ADD_ATTR здесь НЕ нужны — iframe для видео вставляется уже
  // после sanitize, а не через marked/DOMPurify (см. docstring выше).
  let safeHtml = DOMPurify.sanitize(rawHtml);

  for (const { token, html } of placeholders) {
    safeHtml = safeHtml.split(token).join(html);
  }
  return safeHtml;
}
