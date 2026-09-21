import { createTheme, alpha, type ThemeOptions } from '@mui/material/styles';

// ── Design tokens (TirSkix Academy) — тот же бренд, что и портал
// (learning-portal-main/frontend/src/theme.ts): фиолетовый акцент, шрифты
// Manrope/Open Sans. У портала определён только light-режим — dark ниже
// собран из тех же токенов бренда (акцент, radius, шрифты), но со своей
// нейтральной шкалой для тёмных поверхностей.

const VIOLET_600 = '#7F23CC';
const VIOLET_500 = '#9B4FE0'; // акцент на тёмном фоне — светлее для контраста
const VIOLET_800 = '#57188B';

const FONT_HEADING = '"Manrope", "Segoe UI", system-ui, sans-serif';
const FONT_BODY = '"Open Sans", "Segoe UI", system-ui, sans-serif';
export const FONT_CODE = '"Fira Code", "Cascadia Code", Consolas, monospace';

const shape = { borderRadius: 8 };

const typography: ThemeOptions['typography'] = {
  fontFamily: FONT_HEADING,
  h1: { fontWeight: 700, fontSize: '2.25rem' },
  h2: { fontWeight: 700, fontSize: '1.5rem' },
  h3: { fontWeight: 600, fontSize: '1.15rem' },
  h4: { fontWeight: 700 },
  h5: { fontWeight: 700 },
  h6: { fontWeight: 700 },
  subtitle1: { fontWeight: 600 },
  subtitle2: { fontWeight: 600 },
  body1: { fontFamily: FONT_BODY, fontSize: '0.9375rem', lineHeight: 1.6 },
  body2: { fontFamily: FONT_BODY, fontSize: '0.8125rem' },
  caption: { fontFamily: FONT_BODY, fontSize: '0.75rem' },
  button: { textTransform: 'none', fontWeight: 600 },
};

function componentsFor(mode: 'light' | 'dark', tokens: {
  border: string; surface2: string; accentSurface: string; accentSurfaceHover: string;
}): ThemeOptions['components'] {
  return {
    MuiCssBaseline: {
      styleOverrides: { '*, *::before, *::after': { boxSizing: 'border-box' } },
    },
    MuiPaper: {
      defaultProps: { elevation: 0 },
      styleOverrides: {
        root: { border: `1px solid ${tokens.border}`, backgroundImage: 'none' },
        rounded: { borderRadius: 12 },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          border: `1px solid ${tokens.border}`,
          borderRadius: 12,
          boxShadow: 'none',
          backgroundImage: 'none',
          transition: 'box-shadow 150ms cubic-bezier(0.4, 0, 0.2, 1), border-color 150ms cubic-bezier(0.4, 0, 0.2, 1)',
          '&:hover': { borderColor: mode === 'light' ? '#D3D1C7' : '#4A4658' },
        },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: {
          borderRadius: 8,
          paddingInline: 18,
          minHeight: 40,
          fontFamily: FONT_HEADING,
          fontWeight: 600,
          fontSize: '0.875rem',
          transition: 'background-color 150ms, border-color 150ms, color 150ms',
          '&:active': { transform: 'scale(0.98)' },
        },
        sizeSmall: { borderRadius: 6, paddingInline: 12, minHeight: 32, fontSize: '0.8125rem' },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          fontFamily: FONT_BODY,
          borderRadius: 8,
          '&.Mui-focused .MuiOutlinedInput-notchedOutline': { borderColor: VIOLET_500, borderWidth: 1 },
          '&.Mui-focused': { boxShadow: `0 0 0 3px ${alpha(VIOLET_500, 0.25)}` },
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { borderRadius: 20, fontFamily: FONT_BODY, fontWeight: 500, fontSize: '0.75rem' },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: alpha(mode === 'light' ? '#FFFFFF' : '#1E1D24', 0.85),
          backdropFilter: 'saturate(180%) blur(16px)',
          borderBottom: `1px solid ${tokens.border}`,
          boxShadow: 'none',
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: { backgroundImage: 'none', borderRight: `1px solid ${tokens.border}`, boxShadow: 'none' },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          borderRadius: 8,
          transition: 'background-color 150ms, color 150ms',
          '&.Mui-selected': {
            backgroundColor: tokens.accentSurface,
            '&:hover': { backgroundColor: tokens.accentSurfaceHover },
          },
        },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: { textTransform: 'none', fontFamily: FONT_BODY, fontWeight: 500, fontSize: '0.875rem', minHeight: 44 },
      },
    },
    MuiTabs: {
      styleOverrides: { indicator: { backgroundColor: VIOLET_600, height: 2 } },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: { borderRadius: 999, height: 6, backgroundColor: tokens.surface2 },
        bar: { backgroundColor: VIOLET_600, borderRadius: 999 },
      },
    },
    MuiDivider: { styleOverrides: { root: { borderColor: tokens.border } } },
    MuiAlert: {
      styleOverrides: { root: { borderRadius: 8, fontFamily: FONT_BODY, fontSize: '0.875rem' } },
    },
  };
}

export function getTheme(mode: 'light' | 'dark') {
  if (mode === 'light') {
    const INK_900 = '#1C1B22';
    const INK_600 = '#5F5E5A';
    const INK_100 = '#E7E5DE';
    const INK_50 = '#F1F0EC';
    return createTheme({
      palette: {
        mode: 'light',
        primary: { main: VIOLET_600, dark: VIOLET_800, contrastText: '#FFFFFF' },
        secondary: { main: VIOLET_800 },
        success: { main: '#1D9E75', light: '#E1F5EE', dark: '#085041', contrastText: '#FFFFFF' },
        warning: { main: '#BA7517', light: '#FAEEDA', dark: '#633806', contrastText: '#FFFFFF' },
        error: { main: '#E24B4A', light: '#FCEBEB', dark: '#791F1F', contrastText: '#FFFFFF' },
        info: { main: '#378ADD', light: '#E6F1FB', dark: '#0C447C', contrastText: '#FFFFFF' },
        background: { default: '#FAFAF8', paper: '#FFFFFF' },
        text: { primary: INK_900, secondary: INK_600, disabled: '#8B8980' },
        divider: INK_100,
      },
      shape,
      typography,
      components: componentsFor('light', {
        border: INK_100, surface2: INK_50, accentSurface: '#F5EEFC', accentSurfaceHover: '#E7D3F8',
      }),
    });
  }

  // dark — та же палитра акцента/статусов, нейтральная шкала — тёплый графит
  // в тон "ink", но затемнённый, не чистый чёрный.
  const SURFACE_0 = '#151420';
  const SURFACE_1 = '#1E1D2B';
  const SURFACE_2 = '#272534';
  const BORDER = '#332F44';
  const TEXT_PRIMARY = '#F1F0F5';
  const TEXT_SECONDARY = '#B3AFC2';

  return createTheme({
    palette: {
      mode: 'dark',
      primary: { main: VIOLET_500, dark: VIOLET_600, contrastText: '#FFFFFF' },
      secondary: { main: '#C99BF0' },
      success: { main: '#3DD9A3', light: '#0F2E24', dark: '#1D9E75', contrastText: '#052017' },
      warning: { main: '#F0B342', light: '#332608', dark: '#BA7517', contrastText: '#2B1D02' },
      error: { main: '#F17575', light: '#3A1414', dark: '#E24B4A', contrastText: '#2B0A0A' },
      info: { main: '#6BB2F5', light: '#122436', dark: '#378ADD', contrastText: '#071322' },
      background: { default: SURFACE_0, paper: SURFACE_1 },
      text: { primary: TEXT_PRIMARY, secondary: TEXT_SECONDARY, disabled: '#716C82' },
      divider: BORDER,
    },
    shape,
    typography,
    components: componentsFor('dark', {
      border: BORDER, surface2: SURFACE_2, accentSurface: alpha(VIOLET_500, 0.18), accentSurfaceHover: alpha(VIOLET_500, 0.28),
    }),
  });
}
