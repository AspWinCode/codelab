import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import App from './App';
import CoursePage from './pages/CoursePage';
import ItemEditorPage from './pages/ItemEditorPage';
import { ThemeModeProvider } from './theme/ThemeModeContext';
import './styles.css';
// EDT-005: подсветка кода и рендер LaTeX-формул в предпросмотре. Блоки кода
// в предпросмотре нарочно остаются на фиксированной тёмной теме hljs
// независимо от режима приложения (light/dark) — как в большинстве
// документаций, это читаемее, чем переключать сторонний CSS живьём.
import 'highlight.js/styles/github-dark.css';
import 'katex/dist/katex.min.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeModeProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<App />} />
          <Route path="/courses/:courseId" element={<CoursePage />} />
          <Route path="/items/:itemId/edit" element={<ItemEditorPage />} />
        </Routes>
      </BrowserRouter>
    </ThemeModeProvider>
  </React.StrictMode>,
);
