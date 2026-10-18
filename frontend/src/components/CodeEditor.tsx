import { indentWithTab } from '@codemirror/commands';
import { cpp } from '@codemirror/lang-cpp';
import { python } from '@codemirror/lang-python';
import { sql } from '@codemirror/lang-sql';
import { indentUnit } from '@codemirror/language';
import { EditorView, keymap } from '@codemirror/view';
import { useTheme } from '@mui/material/styles';
import CodeMirror, { type Extension } from '@uiw/react-codemirror';
import { useMemo } from 'react';
import { FONT_CODE } from '../theme';
import { useThemeMode } from '../theme/ThemeModeContext';

// Tab/Shift+Tab "ловят" фокус — иначе клавиатурный пользователь не сможет
// покинуть редактор табом, как в любом другом текстовом поле (см.
// предупреждение самого CodeMirror про indentWithTab). Явный выход по Esc —
// обязательная компенсация, см. запрос методиста 15.10.2026, п.1.
const escapeToBlur = keymap.of([
  {
    key: 'Escape',
    run: (view) => {
      view.contentDOM.blur();
      return true;
    },
  },
]);

const tabIndent = keymap.of([indentWithTab]);

// Все окружения из реестра на бэкенде (app/services/environments.py):
// python3/python3-data/arcade — Python, cpp17 — C++, sql-sqlite — SQL.
function languageExtension(language: string): Extension {
  if (language === 'cpp17') return cpp();
  if (language === 'sql-sqlite') return sql();
  return python();
}

export default function CodeEditor({ value, onChange, language, minHeight = '280px' }: {
  value: string;
  onChange: (value: string) => void;
  language: string;
  minHeight?: string;
}) {
  const { mode } = useThemeMode();
  const theme = useTheme();

  const extensions = useMemo(() => [
    languageExtension(language),
    // 4 пробела — и для авто-отступа после Enter (его даёт сам language
    // package — indentService у python/cpp продолжает отступ предыдущей
    // строки и добавляет уровень после ":"/"{"), и для Tab/Shift+Tab.
    indentUnit.of('    '),
    tabIndent,
    escapeToBlur,
    EditorView.theme({
      '&': { fontSize: '0.875rem' },
      '.cm-content': { fontFamily: FONT_CODE, padding: '12px 0' },
      '.cm-gutters': { fontFamily: FONT_CODE },
      '.cm-scroller': { overflow: 'auto' },
    }),
  ], [language]);

  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      theme={mode}
      minHeight={minHeight}
      maxHeight="600px"
      extensions={extensions}
      basicSetup={{ tabSize: 4 }}
      style={{ borderRadius: 8, overflow: 'hidden', border: `1px solid ${theme.palette.divider}` }}
    />
  );
}
