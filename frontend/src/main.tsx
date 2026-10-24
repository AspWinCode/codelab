import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import App from './App';
import ErrorBoundary from './components/ErrorBoundary';
import CoursePage from './pages/CoursePage';
import ItemEditorPage from './pages/ItemEditorPage';
import { ThemeModeProvider } from './theme/ThemeModeContext';
import './styles.css';
// EDT-005: подсветка кода и рендер LaTeX-формул в предпросмотре. Блоки кода
// Базовая light-палитра hljs переопределяется CSS-токенами для dark mode.
import 'highlight.js/styles/github-dark.css';
import 'katex/dist/katex.min.css';

// Диагностика для случаев, которые ErrorBoundary не ловит (например, ошибка
// внутри промиса) — без токенов/секретов, только для консоли браузера.
window.addEventListener('error', (e) => {
  console.error('[window.error]', e.error?.name, e.error?.message, e.error?.stack, location.href, navigator.userAgent);
});
window.addEventListener('unhandledrejection', (e) => {
  const reason = e.reason;
  console.error('[unhandledrejection]', reason?.name, reason?.message, reason?.stack, location.href, navigator.userAgent);
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <ThemeModeProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<App />} />
            <Route path="/courses/:courseId" element={<CoursePage />} />
            <Route path="/items/:itemId/edit" element={<ItemEditorPage />} />
          </Routes>
        </BrowserRouter>
      </ThemeModeProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);
