import { DarkMode, LightMode } from '@mui/icons-material';
import { AppBar, Box, IconButton, Toolbar, Tooltip, Typography } from '@mui/material';
import { Link } from 'react-router-dom';
import { useThemeMode } from '../theme/ThemeModeContext';

export default function Layout({ children, actions }: { children: React.ReactNode; actions?: React.ReactNode }) {
  const { mode, toggle } = useThemeMode();

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <AppBar position="sticky" color="transparent" elevation={0}>
        <Toolbar sx={{ gap: 1 }}>
          <Typography
            component={Link}
            to="/"
            variant="h3"
            sx={{ color: 'text.primary', textDecoration: 'none', flexGrow: 1, letterSpacing: -0.5 }}
          >
            Codelab
          </Typography>
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
