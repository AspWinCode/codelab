import { ArrowBack, DarkMode, LightMode } from '@mui/icons-material';
import { AppBar, Box, Button, IconButton, Toolbar, Tooltip, Typography } from '@mui/material';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useThemeMode } from '../theme/ThemeModeContext';

// Единственный путь входа на этот фронтенд — SSO-редирект из кабинета
// ученика (LMS всегда подписывает role="student" в токене, см. kodex_sso.py
// в learning-portal-main) — Studio методиста/тренера работает через
// отдельный прокси-API и не заходит в этот SPA. Фолбэк на случай, если
// сессия Codelab истекла именно на этой вкладке: запоминаем, что последний
// успешный /me был учеником, чтобы кнопка возврата не пропадала после 401
// (п.21 — работает без активной сессии Codelab, это обычная навигация).
const LAST_ROLE_KEY = 'codelab_last_known_role';
const DEFAULT_STUDENT_PORTAL_URL = 'https://tirskix.space/student-portal';

export default function Layout({ children, actions }: { children: React.ReactNode; actions?: React.ReactNode }) {
  const { mode, toggle } = useThemeMode();
  const [isStudent, setIsStudent] = useState(() => {
    try {
      return sessionStorage.getItem(LAST_ROLE_KEY) === 'student';
    } catch {
      return false;
    }
  });
  const [returnTo, setReturnTo] = useState<string | null>(null);

  useEffect(() => {
    api.me().then((me) => {
      const studentNow = me.role === 'student';
      setIsStudent(studentNow);
      setReturnTo(me.return_to_url);
      try {
        if (studentNow) sessionStorage.setItem(LAST_ROLE_KEY, 'student');
        else sessionStorage.removeItem(LAST_ROLE_KEY);
      } catch {
        // localStorage/sessionStorage недоступны (приватный режим и т.п.) —
        // не критично, просто не переживёт истечение сессии на этой вкладке.
      }
    }).catch(() => {
      // 401 и т.п. — оставляем isStudent как есть (значение из sessionStorage
      // с прошлого успешного /me), returnTo остаётся null → сработает дефолт.
    });
  }, []);

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <AppBar position="sticky" color="transparent" elevation={0}>
        <Toolbar sx={{ gap: 1 }}>
          {isStudent && (
            <Button
              href={returnTo || DEFAULT_STUDENT_PORTAL_URL}
              startIcon={<ArrowBack fontSize="small" />}
              color="inherit"
              size="small"
              sx={{ textTransform: 'none', flexShrink: 0 }}
            >
              <Box component="span" sx={{ display: { xs: 'none', sm: 'inline' } }}>Назад в кабинет</Box>
              <Box component="span" sx={{ display: { xs: 'inline', sm: 'none' } }}>Кабинет</Box>
            </Button>
          )}

          {isStudent ? (
            // Ученик не должен уходить с текущего задания случайным кликом
            // по логотипу — ни ссылки, ни onClick, ни role=button, ни
            // активации с клавиатуры (п.2/6): обычный статичный текст.
            <Typography variant="h3" sx={{ color: 'text.primary', flexGrow: 1, letterSpacing: -0.5, cursor: 'default' }}>
              Codelab
            </Typography>
          ) : (
            <Typography
              component={Link}
              to="/"
              variant="h3"
              sx={{ color: 'text.primary', textDecoration: 'none', flexGrow: 1, letterSpacing: -0.5 }}
            >
              Codelab
            </Typography>
          )}
          {actions}
          <Tooltip title={mode === 'light' ? 'Тёмная тема' : 'Светлая тема'}>
            <IconButton onClick={toggle} color="inherit" aria-label="Переключить тему">
              {mode === 'light' ? <DarkMode fontSize="small" /> : <LightMode fontSize="small" />}
            </IconButton>
          </Tooltip>
        </Toolbar>
      </AppBar>
      <Box component="main">{children}</Box>
    </Box>
  );
}
