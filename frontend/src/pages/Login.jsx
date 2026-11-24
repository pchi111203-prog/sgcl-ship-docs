import { useState } from 'react'
import { api, auth } from '../api'

export default function Login({ onLogin }) {
  const [username, setU] = useState('')
  const [password, setP] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setErr('')
    try {
      const r = await api('/api/login', { method: 'POST', body: { username, password } })
      auth.token = r.token
      onLogin(r.user)
    } catch (ex) { setErr(ex.message) } finally { setBusy(false) }
  }
  return (
    <div className="login-wrap">
      <form className="login" onSubmit={submit}>
        <div style={{ textAlign: 'center', marginBottom: 22 }}>
          <img src="/sgcl-logo-light.png" alt="SGCL NSW Assist" style={{ width: 260, maxWidth: '100%', height: 'auto' }} />
          <div className="small muted" style={{ marginTop: 6 }}>Ship Documentation Automation System</div>
        </div>
        {err && <div className="alert red">{err}</div>}
        <div className="field"><label className="f">Tên đăng nhập</label><input value={username} onChange={(e) => setU(e.target.value)} autoFocus /></div>
        <div className="field"><label className="f">Mật khẩu</label><input type="password" value={password} onChange={(e) => setP(e.target.value)} /></div>
        <button className="btn primary" style={{ width: '100%', justifyContent: 'center' }} disabled={busy}>{busy ? 'Đang đăng nhập…' : 'Đăng nhập'}</button>
        <p className="small muted" style={{ marginTop: 16 }}>Tài khoản do quản trị hệ thống cấp. Lần cài đặt đầu tiên: xem mật khẩu khởi tạo trong log máy chủ hoặc file <code>initial_credentials.txt</code>.</p>
      </form>
    </div>
  )
}
