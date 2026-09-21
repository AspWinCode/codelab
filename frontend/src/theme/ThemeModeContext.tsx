import { CssBaseline, ThemeProvider } from '@mui/material';
import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { getTheme } from '../theme';

type Mode = 'light' | 'dark';

const STORAGE_KEY = 'codelab-theme-mode';

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches;
}

function loadStoredMode(): Mode | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === 'light' || v === 'dark' ? v : null;
  } catch {
    return null; // приватный режим/заблокировано — просто не запоминаем выбор
  }
}

const ThemeModeCtx = createContext<{ mode: Mode; toggle: () => void }>({ mode: 'dark', toggle: () => {} });

export const useThemeMode = () => useContext(ThemeModeCtx);

export function ThemeModeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setMode] = useState<Mode>(() => loadStoredMode() ?? (systemPrefersDark() ? 'dark' : 'light'));

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      // приватный режим/заблокировано хранилище — переключатель всё равно работает в рамках сессии
    }
  }, [mode]);

  const toggle = () => setMode((m) => (m === 'light' ? 'dark' : 'light'));
  const theme = useMemo(() => getTheme(mode), [mode]);

  return (
    <ThemeModeCtx.Provider value={{ mode, toggle }}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </ThemeProvider>
    </ThemeModeCtx.Provider>
  );
}
