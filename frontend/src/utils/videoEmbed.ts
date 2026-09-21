/** EDT-004: вставка видео через embed-ссылки с allowlist доменов — YouTube,
 * VK Видео, RuTube (список согласован владельцем продукта 2026-09-21).
 * Возвращает канонический embed-URL, СОБРАННЫЙ НАМИ из извлечённого id, а не
 * исходную ссылку методиста как есть — так вставить произвольный HTML/URL
 * через это поле невозможно, даже если сам вызывающий код забудет
 * экранирование (см. utils/renderContent.tsx). */

export type VideoProvider = 'youtube' | 'vk' | 'rutube';

export interface ResolvedVideoEmbed {
  provider: VideoProvider;
  embedUrl: string;
}

const YOUTUBE_ID_RE = /^[A-Za-z0-9_-]{6,20}$/;
const RUTUBE_ID_RE = /^[a-f0-9]{20,40}$/i;
const VK_IDS_RE = /video(-?\d+)_(\d+)/;

function stripWww(host: string): string {
  return host.replace(/^www\./, '').toLowerCase();
}

function resolveYoutube(url: URL): ResolvedVideoEmbed | null {
  const host = stripWww(url.hostname);
  if (!['youtube.com', 'm.youtube.com', 'youtu.be'].includes(host)) return null;

  let id = '';
  if (host === 'youtu.be') {
    id = url.pathname.slice(1);
  } else if (url.pathname === '/watch') {
    id = url.searchParams.get('v') || '';
  } else if (url.pathname.startsWith('/embed/')) {
    id = url.pathname.slice('/embed/'.length);
  } else if (url.pathname.startsWith('/shorts/')) {
    id = url.pathname.slice('/shorts/'.length);
  }
  id = id.split('/')[0].split('?')[0];

  if (!YOUTUBE_ID_RE.test(id)) return null;
  return { provider: 'youtube', embedUrl: `https://www.youtube.com/embed/${id}` };
}

function resolveRutube(url: URL): ResolvedVideoEmbed | null {
  if (stripWww(url.hostname) !== 'rutube.ru') return null;
  const match = url.pathname.match(/^\/(?:video|play\/embed)\/([a-f0-9]{20,40})\/?/i);
  if (!match) return null;
  const id = match[1];
  if (!RUTUBE_ID_RE.test(id)) return null;
  return { provider: 'rutube', embedUrl: `https://rutube.ru/play/embed/${id}/` };
}

function resolveVk(url: URL): ResolvedVideoEmbed | null {
  const host = stripWww(url.hostname);
  if (!['vk.com', 'vkvideo.ru', 'vk.ru'].includes(host)) return null;

  if (url.pathname === '/video_ext.php') {
    const oid = url.searchParams.get('oid') || '';
    const id = url.searchParams.get('id') || '';
    if (/^-?\d+$/.test(oid) && /^\d+$/.test(id)) {
      return { provider: 'vk', embedUrl: `https://vk.com/video_ext.php?oid=${oid}&id=${id}` };
    }
    return null;
  }

  const match = url.pathname.match(VK_IDS_RE) || url.href.match(VK_IDS_RE);
  if (!match) return null;
  const [, oid, id] = match;
  return { provider: 'vk', embedUrl: `https://vk.com/video_ext.php?oid=${oid}&id=${id}` };
}

export function resolveVideoEmbed(rawUrl: string): ResolvedVideoEmbed | null {
  let url: URL;
  try {
    url = new URL(rawUrl.trim());
  } catch {
    return null;
  }
  if (url.protocol !== 'https:') return null;

  return resolveYoutube(url) || resolveRutube(url) || resolveVk(url);
}
