import React, { useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import './styles.css'
import { api, auth } from './api'
import { ToastProvider, VoyageGate, workVoyage } from './components'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import { VoyageList, VoyageForm, VoyageBin } from './pages/Voyages'
import Documents from './pages/Documents'
import CrossCheck from './pages/CrossCheck'
import Review from './pages/Review'
import Export from './pages/Export'
import History from './pages/History'
import Settings from './pages/Settings'

const NAV = [
  { to: '/', label: 'Dashboard', n: 1, end: true },
  { to: '/voyages', label: 'Quản lý chuyến tàu', n: 2, end: true },
  { to: '/voyages/new', label: 'Tạo chuyến tàu mới', n: 3 },
  { sep: 'Xử lý chuyến tàu' },
  { to: '/work/documents', label: 'Xử lý chứng từ', n: 4, match: 'documents' },
  { to: '/work/crosscheck', label: 'Đối chiếu dữ liệu', n: 5, match: 'crosscheck' },
  { to: '/work/review', label: 'Kiểm tra và xác nhận', n: 6, match: 'review' },
  { to: '/work/export', label: 'Xuất file Excel NSW', n: 7, match: 'export' },
  { sep: 'Hệ thống' },
  { to: '/history', label: 'Lịch sử xử lý', n: 8 },
  { to: '/archive', label: 'Lưu trữ', n: 9 },
  { to: '/trash', label: 'Thùng rác', n: 10 },
  { to: '/settings', label: 'Cài đặt hệ thống', n: 11 },
]

function Shell({ user, onLogout, children }) {
  const path = useLocation().pathname
  const cur = (path.match(/^\/voyages\/(\d+)\/(documents|crosscheck|review|export)$/) || [])[1]   // voyage being viewed
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><img src="/sgcl-logo-dark.png" alt="SGCL NSW Assist" /></div>
        <nav className="nav">
          {NAV.map((n, i) => n.sep ? <div key={i} className="sep">{n.sep}</div> : (
            <NavLink key={n.to} to={n.match && cur ? `/voyages/${cur}/${n.match}` : n.to} end={n.end}
              className={({ isActive }) => (isActive || (n.match && path.startsWith('/voyages/') && path.endsWith('/' + n.match)) ? 'active' : '')}>
              <span className="num">{n.n}</span>{n.label}
            </NavLink>
          ))}
        </nav>
        <div className="user">
          <div><b style={{ color: '#fff' }}>{user.full_name}</b></div>
          <div className="small" style={{ color: '#99d5cb' }}>{user.username} · {user.role === 'supervisor' ? 'Admin Workspace' : 'Staff Workspace'}</div>
          <button className="btn sm" onClick={onLogout}>Đăng xuất</button>
        </div>
      </aside>
      <main className="main">
        <div className="topbar">
          <div className="ctx"><b style={{ color: 'var(--teal-800)' }}>Công ty CP Dịch vụ Tiếp vận và Thương mại Sài Gòn Cửu Long</b><span className="muted small">· Bộ phận Đại lý tàu biển</span></div>
          <div className="spacer" />
          <span className="small muted">Hệ thống trích xuất tự động & Tạo TemplateNSW</span>
        </div>
        <div className="content">{children}</div>
      </main>
    </div>
  )
}

function App() {
  const [user, setUser] = useState(undefined)
  const nav = useNavigate()
  useEffect(() => {
    if (!auth.token) { setUser(null); return }
    api('/api/me').then(setUser).catch(() => setUser(null))
  }, [])
  if (user === undefined) return null
  if (!user) return <Routes><Route path="*" element={<Login onLogin={(u) => { workVoyage.clear(); setUser(u); nav('/') }} />} /></Routes>
  const logout = async () => { await api('/api/logout', { method: 'POST' }).catch(() => {}); auth.token = null; workVoyage.clear(); setUser(null); nav('/login') }
  return (
    <Shell user={user} onLogout={logout}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/login" element={<Navigate to="/" />} />
        <Route path="/voyages" element={<VoyageList user={user} />} />
        <Route path="/voyages/new" element={<VoyageForm />} />
        <Route path="/voyages/:id/edit" element={<VoyageForm />} />
        <Route path="/voyages/:id/documents" element={<Documents />} />
        <Route path="/voyages/:id/crosscheck" element={<CrossCheck />} />
        <Route path="/voyages/:id/review" element={<Review />} />
        <Route path="/voyages/:id/export" element={<Export user={user} />} />
        <Route path="/work/:step" element={<WorkRedirect />} />
        <Route path="/history" element={<History />} />
        <Route path="/archive" element={<VoyageBin user={user} scope="archived" />} />
        <Route path="/trash" element={<VoyageBin user={user} scope="trash" />} />
        <Route path="/settings" element={<Settings user={user} />} />
        <Route path="*" element={<div className="empty">Không tìm thấy trang</div>} />
      </Routes>
    </Shell>
  )
}

function WorkRedirect() {
  const step = window.location.pathname.split('/').pop()
  return <VoyageGate key={step} target={step} />
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode><BrowserRouter><ToastProvider><App /></ToastProvider></BrowserRouter></React.StrictMode>,
)
