import { Notifications as NotificationsIcon } from '@mui/icons-material';
import {
  Alert, Badge, Box, Card, CardActionArea, CardContent, Checkbox, Chip, Container,
  Divider, FormControlLabel, IconButton, LinearProgress, List, ListItem, ListItemText,
  Menu, Stack, Typography,
} from '@mui/material';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, Course, Dashboard, Me, Notification, NotificationPreference } from './api';
import Layout from './components/Layout';

const formatDeadline = (iso: string) => new Date(iso).toLocaleDateString('ru-RU');

/** NTF-001/003: колокольчик уведомлений + настройка необязательных типов. */
function NotificationsMenu() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [prefs, setPrefs] = useState<NotificationPreference[]>([]);
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);

  useEffect(() => {
    api.notifications().then(setNotifications).catch(() => {});
    api.notificationPreferences().then(setPrefs).catch(() => {});
  }, []);

  const unreadCount = notifications.filter((n) => !n.is_read).length;

  const markRead = async (id: number) => {
    await api.markNotificationRead(id).catch(() => {});
    setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, is_read: true } : n)));
  };

  const togglePref = async (type: string, enabled: boolean) => {
    await api.updateNotificationPreference(type, enabled).catch(() => {});
    setPrefs((prev) => prev.map((p) => (p.type === type ? { ...p, enabled } : p)));
  };

  return (
    <>
      <IconButton color="inherit" onClick={(e) => setAnchorEl(e.currentTarget)} aria-label="Уведомления">
        <Badge badgeContent={unreadCount} color="primary" overlap="circular">
          <NotificationsIcon fontSize="small" />
        </Badge>
      </IconButton>
      <Menu anchorEl={anchorEl} open={!!anchorEl} onClose={() => setAnchorEl(null)} PaperProps={{ sx: { width: 340, maxHeight: 480 } }}>
        {notifications.length === 0 ? (
          <Box sx={{ p: 2 }}>
            <Typography variant="body2" color="text.secondary">Уведомлений пока нет.</Typography>
          </Box>
        ) : (
          <List dense disablePadding>
            {notifications.map((n) => (
              <ListItem
                key={n.id}
                onClick={() => !n.is_read && markRead(n.id)}
                sx={{ opacity: n.is_read ? 0.55 : 1, cursor: n.is_read ? 'default' : 'pointer', alignItems: 'flex-start' }}
              >
                <ListItemText
                  primary={n.title}
                  secondary={
                    <>
                      {n.body && <Typography variant="body2" component="span" sx={{ display: 'block' }}>{n.body}</Typography>}
                      <Typography variant="caption" color="text.secondary">{new Date(n.created_at).toLocaleString('ru-RU')}</Typography>
                    </>
                  }
                />
              </ListItem>
            ))}
          </List>
        )}
        {prefs.some((p) => !p.mandatory) && (
          <>
            <Divider />
            <Box sx={{ p: 1.5 }}>
              {prefs.filter((p) => !p.mandatory).map((p) => (
                <FormControlLabel
                  key={p.type}
                  control={<Checkbox size="small" checked={p.enabled} onChange={(e) => togglePref(p.type, e.target.checked)} />}
                  label={<Typography variant="body2">Напоминание о дедлайне</Typography>}
                />
              ))}
            </Box>
          </>
        )}
      </Menu>
    </>
  );
}

function VerdictChip({ verdict, score }: { verdict: string | null; score: number | null }) {
  if (!verdict) return <Chip size="small" label="проверяется" />;
  const color = verdict === 'Accepted' ? 'success' : verdict === 'Wrong Answer' ? 'error' : 'warning';
  return <Chip size="small" color={color} label={score !== null ? `${verdict} · ${score}` : verdict} />;
}

/** STU-001: главная страница ученика — активные курсы, процент прохождения,
 * ближайшие дедлайны, последние результаты, следующий рекомендуемый шаг.
 * Для не-студентов (методист/тренер/админ) — просто список курсов. */
export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [courses, setCourses] = useState<Course[]>([]);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  useEffect(() => {
    api
      .me()
      .then((m) => {
        setMe(m);
        if (m.role === 'student') {
          api.dashboard().then(setDashboard).catch(() => {});
        } else {
          api.courses().then(setCourses).catch(() => {});
        }
      })
      .catch(() => setError('Не авторизован — войдите через портал (SSO)'));
  }, []);

  if (error) {
    return (
      <Layout>
        <Container maxWidth="sm" sx={{ pt: 10 }}>
          <Alert severity="warning">{error}</Alert>
        </Container>
      </Layout>
    );
  }

  return (
    <Layout actions={me && <NotificationsMenu />}>
      <Container maxWidth="md" sx={{ py: 4 }}>
        {me && (
          <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
            Привет, {me.full_name}
            {me.groups.length > 0 ? ` · ${me.groups.join(', ')}` : ''}
          </Typography>
        )}

        {me?.role === 'student' ? (
          <>
            <Typography variant="h2" sx={{ mb: 2 }}>Мои курсы</Typography>
            {!dashboard || dashboard.courses.length === 0 ? (
              <Typography color="text.secondary">Пока нет назначенных курсов.</Typography>
            ) : (
              <Stack spacing={2} sx={{ mb: 5 }}>
                {dashboard.courses.map((c) => (
                  <Card key={c.course_id}>
                    <CardActionArea
                      onClick={() => navigate(c.last_item_id ? `/courses/${c.course_id}?item=${c.last_item_id}` : `/courses/${c.course_id}`)}
                    >
                      <CardContent>
                        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 1 }}>
                          <Typography variant="subtitle1">{c.title}</Typography>
                          {c.deadline && (
                            <Chip size="small" variant="outlined" label={`дедлайн: ${formatDeadline(c.deadline)}`} />
                          )}
                        </Stack>
                        <LinearProgress variant="determinate" value={c.percent} sx={{ mb: 1 }} />
                        <Typography variant="body2" color="text.secondary">
                          {c.completed_items} / {c.total_items} заданий · {c.percent}%
                        </Typography>
                        {c.next_item && (
                          <Typography variant="body2" sx={{ mt: 1 }}>
                            Дальше: <Box component="span" sx={{ color: 'primary.main', fontWeight: 600 }}>{c.next_item.title}</Box>
                          </Typography>
                        )}
                      </CardContent>
                    </CardActionArea>
                  </Card>
                ))}
              </Stack>
            )}

            <Typography variant="h2" sx={{ mb: 2 }}>Последние результаты</Typography>
            {!dashboard || dashboard.recent_results.length === 0 ? (
              <Typography color="text.secondary">Пока нет проверенных посылок.</Typography>
            ) : (
              <Card>
                <List disablePadding>
                  {dashboard.recent_results.map((r, i) => (
                    <ListItem key={r.submission_id} divider={i < dashboard.recent_results.length - 1}>
                      <ListItemText primary={r.task_title} />
                      <VerdictChip verdict={r.verdict} score={r.score} />
                    </ListItem>
                  ))}
                </List>
              </Card>
            )}
          </>
        ) : (
          <>
            <Typography variant="h2" sx={{ mb: 2 }}>Курсы</Typography>
            {courses.length === 0 ? (
              <Typography color="text.secondary">Пока нет доступных курсов.</Typography>
            ) : (
              <Stack spacing={1.5}>
                {courses.map((c) => (
                  <Card key={c.id}>
                    <CardActionArea onClick={() => navigate(`/courses/${c.id}`)}>
                      <CardContent>
                        <Typography variant="subtitle1">{c.title}</Typography>
                      </CardContent>
                    </CardActionArea>
                  </Card>
                ))}
              </Stack>
            )}
          </>
        )}
      </Container>
    </Layout>
  );
}
