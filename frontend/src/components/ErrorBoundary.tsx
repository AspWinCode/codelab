import { Alert, Box, Button, Container, Typography } from '@mui/material';
import { Component, type ErrorInfo, type ReactNode } from 'react';

// Известный класс ошибок: расширение/автоперевод браузера (Google Translate
// и т.п.) переписывает текстовые узлы, которыми управляет React, и затем
// React пытается удалить/вставить узел, которого там уже нет с точки зрения
// DOM — "NotFoundError: Failed to execute 'removeChild'/'insertBefore'".
// Для этого конкретного класса показываем пользователю, что делать; для
// остальных ошибок — обычное сообщение, не выдумывая причину.
function isTranslateLikeDomError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  const isDomNotFound = error.name === 'NotFoundError' || /NotFoundError/.test(error.message);
  const touchesReconciliation = /removeChild|insertBefore|replaceChild/.test(error.message);
  return isDomNotFound && touchesReconciliation;
}

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary]', error.name, error.message, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    const translateLike = isTranslateLikeDomError(error);

    return (
      <Container maxWidth="sm" sx={{ pt: 10 }}>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, alignItems: 'flex-start' }}>
          <Alert severity="error" sx={{ width: '100%' }}>
            {translateLike ? (
              <>
                Не удалось отобразить страницу.
                <br />
                Если в браузере включён автоматический перевод, отключите перевод для tirskix.space и обновите страницу.
              </>
            ) : (
              <>Не удалось отобразить страницу. Попробуйте обновить её.</>
            )}
          </Alert>
          <Typography variant="caption" color="text.secondary">
            {error.name}: {error.message}
          </Typography>
          <Button variant="contained" onClick={() => window.location.reload()}>
            Обновить страницу
          </Button>
        </Box>
      </Container>
    );
  }
}
