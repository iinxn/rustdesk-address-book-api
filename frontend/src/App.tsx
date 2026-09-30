import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { getToken } from './api';
import Books from './pages/Books';
import Customers from './pages/Customers';
import Devices from './pages/Devices';
import Login from './pages/Login';
import Tags from './pages/Tags';
import Users from './pages/Users';

function Guard({ children }: { children: React.ReactNode }) {
  return getToken() ? <>{children}</> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Guard><Devices /></Guard>} />
        <Route path="/books" element={<Guard><Books /></Guard>} />
        <Route path="/tags" element={<Guard><Tags /></Guard>} />
        <Route path="/customers" element={<Guard><Customers /></Guard>} />
        <Route path="/users" element={<Guard><Users /></Guard>} />
      </Routes>
    </HashRouter>
  );
}
