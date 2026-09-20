import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import App from './App';
import CoursePage from './pages/CoursePage';
import ItemEditorPage from './pages/ItemEditorPage';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route path="/courses/:courseId" element={<CoursePage />} />
        <Route path="/items/:itemId/edit" element={<ItemEditorPage />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
