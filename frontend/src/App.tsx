import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { getToken } from './api';
import { I18nProvider } from './i18n';
import { NotificationProvider } from './notifications';
import Books from './pages/Books';
import Devices from './pages/Devices';
import Login from './pages/Login';
import Tags from './pages/Tags';
import Users from './pages/Users';

function Guard({ children }: { children: React.ReactNode }) {
  return getToken() ? <>{children}</> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <I18nProvider>
      <NotificationProvider>
        <HashRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/" element={<Guard><Devices /></Guard>} />
            <Route path="/books" element={<Guard><Books /></Guard>} />
            <Route path="/tags" element={<Guard><Tags /></Guard>} />
            <Route path="/users" element={<Guard><Users /></Guard>} />
          </Routes>
        </HashRouter>
      </NotificationProvider>
    </I18nProvider>
  );
}
