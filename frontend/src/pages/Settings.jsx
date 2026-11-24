import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, fileUrl, fmtSize } from '../api'
import { Modal, Spinner, useToast } from '../components'

// Admin Workspace (Khu vực quản trị) – only for supervisor accounts. Staff never see this page.
const TABS = [
  ['accounts', 'Quản lý tài khoản'],
  ['roles', 'Phân quyền'],
  ['catalogs', 'Quản lý danh mục'],
  ['template', 'Quản lý mẫu NSW'],
  ['monitor', 'Giám sát hoạt động'],
  ['stats', 'Thống kê người dùng và hoạt động'],
]
const ROLE = { supervisor: ['Quản trị viên', 'b-teal'], staff: ['Nhân viên', 'b-gray'] }
const ACCESS = {
  LOGIN: ['Đăng nhập', 'b-green'], LOGOUT: ['Đăng xuất', 'b-gray'], LOGIN_FAILED: ['Sai mật khẩu', 'b-amber'],
  LOCKED: ['Bị chặn (sai 5 lần)', 'b-red'], LOGIN_DISABLED: ['Tài khoản đã khóa', 'b-red'],
}
const ACTION = {
  CREATE_VOYAGE: 'Tạo chuyến tàu', EDIT_VOYAGE: 'Sửa chuyến tàu', UPLOAD: 'Tải chứng từ', CROSSCHECK: 'Đối chiếu',
  EXPORT_EXCEL: 'Xuất Excel', TRASH_VOYAGE: 'Chuyển vào thùng rác', RESTORE_VOYAGE: 'Khôi phục chuyến tàu', ARCHIVE_VOYAGE: 'Lưu trữ',
  ADD_FIELD_VALUE: 'Bổ sung dữ liệu', ADD_MANUAL_RECORD: 'Thêm dòng thủ công', EXCLUDE_RECORD: 'Loại bỏ dòng', SET_EXPORT_OPTION: 'Tùy chọn xuất',
  CREATE_USER: 'Tạo tài khoản', EDIT_USER: 'Sửa tài khoản', SET_PASSWORD: 'Đặt lại mật khẩu', FORCE_LOGOUT: 'Buộc đăng xuất',
  TEMPLATE_UPLOAD: 'Thay mẫu NSW', TEMPLATE_RESET: 'Dùng lại mẫu NSW gốc', BACKUP: 'Sao lưu', RESTORE: 'Khôi phục dữ liệu',
  BACKUP_UPLOAD: 'Tải lên bản sao lưu', BACKUP_DELETE: 'Xóa bản sao lưu',
}
const act = (a) => ACTION[a] || a

export default function Settings({ user }) {
  const [tab, setTab] = useState(() => { try { return localStorage.getItem('sgcl.adminTab') || 'accounts' } catch { return 'accounts' } })
  const pick = (t) => { setTab(t); try { localStorage.setItem('sgcl.adminTab', t) } catch { /* ignore */ } }
  if (user.role !== 'supervisor') {
    return (
      <>
        <div className="page-head"><div><div className="small" style={{ color: 'var(--teal-700)', fontWeight: 600, letterSpacing: '.04em' }}>STAFF WORKSPACE</div><h1>Cài đặt hệ thống</h1>
          <p>Mẫu Excel NSW đang dùng, bảng ánh xạ dữ liệu và dữ liệu mẫu để kiểm thử. Việc thay mẫu NSW và các phần quản trị khác do quản trị viên thực hiện.</p></div></div>
        <div className="tabs"><button className="on">Quản lý mẫu NSW</button></div>
        <Template readOnly />
      </>
    )
  }
  return (
    <>
      <div className="page-head"><div><div className="small" style={{ color: 'var(--teal-700)', fontWeight: 600, letterSpacing: '.04em' }}>ADMIN WORKSPACE</div><h1>Khu vực quản trị</h1>
        <p>Tài khoản, phân quyền, danh mục, mẫu NSW, giám sát hoạt động, sao lưu và thống kê. Nhân viên (Staff Workspace) không vào được khu vực này.</p></div></div>
      <div className="tabs">{TABS.map(([k, l]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => pick(k)}>{l}</button>)}</div>
      {tab === 'accounts' && <Accounts me={user} />}
      {tab === 'roles' && <Roles me={user} />}
      {tab === 'catalogs' && <Catalogs />}
      {tab === 'template' && <Template />}
      {tab === 'monitor' && <Monitor />}
      {tab === 'stats' && <Stats />}
    </>
  )
}

// ---------------------------------------------------------------- accounts
function Accounts({ me }) {
  const [users, setUsers] = useState(null)
  const [nu, setNu] = useState({ username: '', full_name: '', password: '', role: 'staff' })
  const [pw, setPw] = useState({ old_password: '', new_password: '' })
  const [edit, setEdit] = useState(null)
  const [reset, setReset] = useState(null)
  const toast = useToast()
  const load = () => api('/api/admin/users').then(setUsers)
  useEffect(() => { load() }, [])
  const run = async (fn, ok) => { try { await fn(); toast(ok); load(); return true } catch (e) { toast(e.message, 'err'); return false } }
  const addUser = () => run(() => api('/api/users', { method: 'POST', body: nu }), 'Đã tạo tài khoản').then((ok) => ok && setNu({ username: '', full_name: '', password: '', role: 'staff' }))
  const lock = (u) => { if (u.active && !confirm(`Khóa tài khoản ${u.username}? Người này sẽ bị đăng xuất và không đăng nhập được cho tới khi mở khóa.`)) return; run(() => api(`/api/admin/users/${u.id}`, { method: 'PUT', body: { active: !u.active } }), u.active ? 'Đã khóa tài khoản' : 'Đã mở khóa tài khoản') }
  const kick = (u) => run(() => api(`/api/admin/users/${u.id}/logout`, { method: 'POST' }), `Đã đăng xuất ${u.username} khỏi mọi thiết bị`)
  const changePw = () => run(() => api('/api/me/password', { method: 'POST', body: pw }), 'Đã đổi mật khẩu').then((ok) => ok && setPw({ old_password: '', new_password: '' }))
  if (!users) return <div className="empty"><Spinner /></div>
  return (
    <>
      <div className="card tight">
        <div className="card-head"><h2>Tài khoản ({users.length})</h2></div>
        <div style={{ overflowX: 'auto' }}><table className="t">
          <thead><tr><th>Tên đăng nhập</th><th>Họ tên</th><th>Vai trò</th><th>Trạng thái</th><th>Đăng nhập gần nhất</th><th>Ngày tạo</th><th style={{ textAlign: 'right' }}>Thao tác</th></tr></thead>
          <tbody>{users.map((u) => (
            <tr key={u.id}>
              <td className="mono"><b>{u.username}</b>{u.id === me.id && <span className="badge b-blue" style={{ marginLeft: 6 }}>Bạn</span>}</td>
              <td>{u.full_name}</td>
              <td><span className={`badge ${ROLE[u.role]?.[1]}`}>{ROLE[u.role]?.[0] || u.role}</span></td>
              <td>{u.active ? <span className="badge b-green">Đang hoạt động</span> : <span className="badge b-red">Đã khóa</span>}{u.online && u.active ? <span className="badge b-teal" style={{ marginLeft: 4 }}>Đang đăng nhập</span> : null}</td>
              <td className="small">{u.last_login || '—'}{u.last_ip ? <div className="muted">IP {u.last_ip}</div> : null}</td>
              <td className="small">{u.created_at}</td>
              <td style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                <button className="btn sm" onClick={() => setEdit({ ...u })}>Sửa</button>{' '}
                <button className="btn sm" onClick={() => setReset({ ...u, pw: '' })}>Đặt lại mật khẩu</button>{' '}
                {u.id !== me.id && u.online && <><button className="btn sm" onClick={() => kick(u)}>Buộc đăng xuất</button>{' '}</>}
                {u.id !== me.id && <button className={`btn sm ${u.active ? 'danger' : 'primary'}`} onClick={() => lock(u)}>{u.active ? 'Khóa' : 'Mở khóa'}</button>}
              </td>
            </tr>))}
          </tbody>
        </table></div>
      </div>
      <div className="grid g2">
        <div className="card">
          <h2>Thêm tài khoản</h2>
          <div className="grid g2">
            <input placeholder="Tên đăng nhập" value={nu.username} onChange={(e) => setNu({ ...nu, username: e.target.value })} />
            <input placeholder="Họ tên" value={nu.full_name} onChange={(e) => setNu({ ...nu, full_name: e.target.value })} />
            <input placeholder="Mật khẩu (≥ 6 ký tự)" type="password" value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} />
            <select value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value })}><option value="staff">Nhân viên (Staff Workspace)</option><option value="supervisor">Quản trị viên (Admin Workspace)</option></select>
          </div>
          <button className="btn primary" style={{ marginTop: 10 }} disabled={!nu.username || !nu.full_name || !nu.password} onClick={addUser}>Thêm tài khoản</button>
        </div>
        <div className="card">
          <h2>Đổi mật khẩu của tôi</h2>
          <div className="grid g2"><input type="password" placeholder="Mật khẩu hiện tại" value={pw.old_password} onChange={(e) => setPw({ ...pw, old_password: e.target.value })} />
            <input type="password" placeholder="Mật khẩu mới (≥ 6 ký tự)" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></div>
          <button className="btn" style={{ marginTop: 10 }} disabled={!pw.old_password || !pw.new_password} onClick={changePw}>Đổi mật khẩu</button>
        </div>
      </div>
      {edit && <Modal title={`Sửa tài khoản ${edit.username}`} onClose={() => setEdit(null)}
        footer={<><button className="btn" onClick={() => setEdit(null)}>Hủy</button><button className="btn primary" onClick={() => run(() => api(`/api/admin/users/${edit.id}`, { method: 'PUT', body: { full_name: edit.full_name, role: edit.role } }), 'Đã lưu').then((ok) => ok && setEdit(null))}>Lưu</button></>}>
        <label className="small muted">Họ tên</label>
        <input style={{ width: '100%', marginBottom: 12 }} value={edit.full_name} onChange={(e) => setEdit({ ...edit, full_name: e.target.value })} />
        <label className="small muted">Vai trò</label>
        <select style={{ width: '100%' }} value={edit.role} disabled={edit.id === me.id} onChange={(e) => setEdit({ ...edit, role: e.target.value })}>
          <option value="staff">Nhân viên (Staff Workspace)</option><option value="supervisor">Quản trị viên (Admin Workspace)</option></select>
        {edit.id === me.id && <div className="small muted" style={{ marginTop: 6 }}>Không tự hạ quyền tài khoản đang đăng nhập.</div>}
      </Modal>}
      {reset && <Modal title={`Đặt lại mật khẩu – ${reset.username}`} onClose={() => setReset(null)}
        footer={<><button className="btn" onClick={() => setReset(null)}>Hủy</button><button className="btn primary" disabled={reset.pw.length < 6} onClick={() => run(() => api(`/api/admin/users/${reset.id}/password`, { method: 'POST', body: { new_password: reset.pw } }), 'Đã đặt lại mật khẩu').then((ok) => ok && setReset(null))}>Đặt mật khẩu</button></>}>
        <p className="small muted">Nhập mật khẩu mới (ít nhất 6 ký tự) rồi báo lại cho người dùng. {reset.id !== me.id && 'Các phiên đăng nhập hiện tại của tài khoản này sẽ bị đăng xuất.'}</p>
        <input type="password" style={{ width: '100%' }} placeholder="Mật khẩu mới" value={reset.pw} onChange={(e) => setReset({ ...reset, pw: e.target.value })} />
      </Modal>}
    </>
  )
}

// ---------------------------------------------------------------- roles
function Roles({ me }) {
  const [p, setP] = useState(null)
  const [users, setUsers] = useState([])
  const toast = useToast()
  const load = () => { api('/api/admin/permissions').then(setP); api('/api/admin/users').then(setUsers) }
  useEffect(load, [])
  const setRole = async (u, role) => { try { await api(`/api/admin/users/${u.id}`, { method: 'PUT', body: { role } }); toast(`Đã đổi vai trò của ${u.username}`) } catch (e) { toast(e.message, 'err') } load() }
  if (!p) return <div className="empty"><Spinner /></div>
  let last = ''
  return (
    <div className="grid g2" style={{ alignItems: 'start' }}>
      <div className="card tight">
        <div className="card-head"><h2>Quyền theo vai trò</h2></div>
        <table className="t">
          <thead><tr><th>Chức năng</th><th style={{ textAlign: 'center' }}>Nhân viên<div className="small muted">Staff Workspace</div></th><th style={{ textAlign: 'center' }}>Quản trị viên<div className="small muted">Admin Workspace</div></th></tr></thead>
          <tbody>{p.matrix.flatMap((m) => {
            const head = m.group !== last ? [<tr key={m.group}><td colSpan={3} style={{ background: 'var(--gray-bg)', fontWeight: 600, fontSize: 12.5 }}>{m.group}</td></tr>] : []
            last = m.group
            return [...head, <tr key={m.action}><td>{m.action}</td>
              <td style={{ textAlign: 'center' }}>{m.staff ? <span className="badge b-green">Có</span> : <span className="badge b-gray">Không</span>}</td>
              <td style={{ textAlign: 'center' }}>{m.supervisor ? <span className="badge b-green">Có</span> : <span className="badge b-gray">Không</span>}</td></tr>]
          })}</tbody>
        </table>
      </div>
      <div className="card tight">
        <div className="card-head"><h2>Gán vai trò cho tài khoản</h2></div>
        <table className="t">
          <thead><tr><th>Tài khoản</th><th>Họ tên</th><th>Vai trò</th></tr></thead>
          <tbody>{users.map((u) => <tr key={u.id}><td className="mono">{u.username}</td><td>{u.full_name}</td>
            <td><select value={u.role} disabled={u.id === me.id} onChange={(e) => setRole(u, e.target.value)}>
              <option value="staff">Nhân viên</option><option value="supervisor">Quản trị viên</option></select></td></tr>)}</tbody>
        </table>
        <p className="small muted" style={{ padding: '0 16px 12px' }}>Nhân viên chỉ đăng nhập và thao tác với chuyến tàu, chứng từ và biểu mẫu; không cài đặt hay chỉnh sửa hệ thống. Luôn phải còn ít nhất một quản trị viên đang hoạt động.</p>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- catalogs
function Catalogs() {
  const [list, setList] = useState(null)
  const [name, setName] = useState('ranks')
  const [q, setQ] = useState('')
  const [data, setData] = useState(null)
  const [vessels, setVessels] = useState([])
  const [ves, setVes] = useState(null)
  const toast = useToast()
  const loadVessels = () => api('/api/vessels').then(setVessels)
  useEffect(() => { api('/api/admin/catalogs').then(setList); loadVessels() }, [])
  useEffect(() => {
    if (name === 'vessels') return
    const t = setTimeout(() => api(`/api/admin/catalogs/${name}?q=${encodeURIComponent(q)}`).then(setData), 200)
    return () => clearTimeout(t)
  }, [name, q])
  const saveVessel = async () => {
    try { await api(`/api/vessels/${ves.id}`, { method: 'PUT', body: ves }); toast('Đã lưu hồ sơ tàu'); setVes(null); loadVessels() } catch (e) { toast(e.message, 'err') }
  }
  if (!list) return <div className="empty"><Spinner /></div>
  const vq = q.trim().toUpperCase()
  const shownVessels = vessels.filter((v) => !vq || `${v.vessel_name} ${v.imo || ''} ${v.call_sign || ''}`.toUpperCase().includes(vq))
  return (
    <div className="grid" style={{ gridTemplateColumns: '260px minmax(0,1fr)', alignItems: 'start' }}>
      <div className="card tight">
        <div className="card-head"><h2>Danh mục</h2></div>
        {[...list, { name: 'vessels', label: 'Hồ sơ tàu', count: vessels.length }].map((c) => (
          <button key={c.name} className="btn ghost" style={{ display: 'flex', width: '100%', justifyContent: 'space-between', borderRadius: 0, padding: '9px 16px', background: name === c.name ? 'var(--teal-50)' : 'none', fontWeight: name === c.name ? 600 : 400 }}
            onClick={() => { setName(c.name); setQ(''); setData(null) }}><span>{c.label}</span><span className="muted small">{c.count}</span></button>))}
      </div>
      <div className="card tight">
        <div className="card-head" style={{ gap: 12 }}>
          <h2>{name === 'vessels' ? 'Hồ sơ tàu' : data?.label || '…'}</h2>
          <input style={{ maxWidth: 320 }} placeholder="Tìm theo mã hoặc tên…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {name === 'vessels' ? (
          <>
            <p className="small muted" style={{ padding: '0 16px' }}>Hồ sơ tàu chỉ lưu thông tin nhận diện tàu, tách biệt với dữ liệu từng chuyến. Nhân viên lưu hồ sơ khi tạo chuyến tàu mới; quản trị viên chỉnh sửa tại đây.</p>
            <div className="scroll" style={{ maxHeight: 520 }}><table className="t"><thead><tr><th>Tên tàu</th><th>IMO</th><th>Call sign</th><th>Quốc tịch</th><th>GT</th><th>NT</th><th>Số chuyến</th><th /></tr></thead><tbody>
              {shownVessels.map((v) => <tr key={v.id}><td><b>{v.vessel_name}</b></td><td>{v.imo || '—'}</td><td>{v.call_sign || '—'}</td><td>{v.flag || '—'}</td><td>{v.gross_tonnage || '—'}</td><td>{v.net_tonnage || '—'}</td><td>{v.voyages}</td>
                <td><button className="btn sm" onClick={() => setVes({ ...v })}>Sửa</button></td></tr>)}
              {!shownVessels.length && <tr><td colSpan={8} className="empty">Chưa có hồ sơ tàu.</td></tr>}
            </tbody></table></div>
          </>
        ) : !data ? <div className="empty"><Spinner /></div> : (
          <>
            <p className="small muted" style={{ padding: '0 16px' }}>
              {['ports', 'countries'].includes(name) ? 'Danh mục chuẩn quốc tế đi kèm hệ thống, dùng để tự điền mã cảng và mã quốc gia khi xuất NSW.' : 'Lấy từ sheet Declaration list của mẫu NSW đang dùng. Muốn cập nhật danh mục này, thay mẫu NSW mới ở thẻ Quản lý mẫu NSW.'}
              {' '}Hiện {data.items.length} / {data.total} mục.</p>
            <div className="scroll" style={{ maxHeight: 520 }}><table className="t"><thead><tr><th style={{ width: 140 }}>Mã</th><th>Tên</th></tr></thead><tbody>
              {data.items.map((x) => <tr key={x.code + x.name}><td className="mono">{x.code}</td><td>{x.name || '—'}</td></tr>)}
              {!data.items.length && <tr><td colSpan={2} className="empty">Không tìm thấy.</td></tr>}
            </tbody></table></div>
          </>
        )}
      </div>
      {ves && <Modal title={`Sửa hồ sơ tàu ${ves.vessel_name}`} onClose={() => setVes(null)}
        footer={<><button className="btn" onClick={() => setVes(null)}>Hủy</button><button className="btn primary" onClick={saveVessel}>Lưu</button></>}>
        <div className="grid g2">{[['vessel_name', 'Tên tàu'], ['imo', 'IMO'], ['call_sign', 'Call sign'], ['flag', 'Quốc tịch'], ['gross_tonnage', 'Gross tonnage'], ['net_tonnage', 'Net tonnage']].map(([k, l]) => (
          <div key={k}><label className="small muted">{l}</label><input style={{ width: '100%' }} value={ves[k] || ''} onChange={(e) => setVes({ ...ves, [k]: e.target.value })} /></div>))}</div>
      </Modal>}
    </div>
  )
}

// ---------------------------------------------------------------- NSW template
function Template({ readOnly = false }) {
  const [t, setT] = useState(null)
  const [s, setS] = useState(null)
  const [busy, setBusy] = useState(0)
  const toast = useToast()
  const nav = useNavigate()
  const load = () => { api('/api/admin/template').then(setT); api('/api/settings').then(setS) }
  useEffect(load, [])
  const upload = async (file) => {
    if (!file) return
    const form = new FormData(); form.append('file', file)
    setBusy(-1)
    try { await api('/api/admin/template', { method: 'POST', form }); toast('Đã thay mẫu NSW. Các file xuất từ bây giờ dùng mẫu mới.'); load() } catch (e) { toast(e.message, 'err') } finally { setBusy(0) }
  }
  const resetTpl = async () => {
    if (!confirm('Dùng lại mẫu NSW gốc của hệ thống? Mẫu đang dùng sẽ được cất vào thư mục sao lưu.')) return
    try { await api('/api/admin/template', { method: 'DELETE' }); toast('Đã dùng lại mẫu NSW gốc'); load() } catch (e) { toast(e.message, 'err') }
  }
  const sample = async (n) => {
    setBusy(n)
    try { const r = await api(`/api/samples/${n}`, { method: 'POST' }); toast(`Đã tạo chuyến DỮ LIỆU MẪU – tình huống ${n}`); nav(`/voyages/${r.voyage_id}/documents`) }
    catch (e) { toast(e.message, 'err') } finally { setBusy(0) }
  }
  if (!t || !s) return <div className="empty"><Spinner /></div>
  return (
    <>
      <div className="grid g2" style={{ alignItems: 'start' }}>
        <div className="card">
          <h2>Mẫu Excel NSW đang dùng</h2>
          <dl className="kv">
            <dt>File mẫu</dt><dd className="mono">{t.file} {t.custom ? <span className="badge b-blue">Mẫu đã thay</span> : <span className="badge b-teal">Mẫu gốc của hệ thống</span>}</dd>
            <dt>Cập nhật lúc</dt><dd>{t.modified}</dd>
            <dt>Dung lượng</dt><dd>{fmtSize(t.size)}</dd>
            <dt>Số sheet</dt><dd>{t.sheets.length}</dd>
            <dt>Danh mục mã</dt><dd className="small">{Object.entries(t.codes).map(([k, v]) => `${k}: ${v}`).join(' · ')}</dd>
          </dl>
          <div className="small" style={{ marginTop: 10 }}>{t.sheets.map((n, i) => <span key={n} className={`badge ${t.states[n] === 'hidden' ? 'b-gray' : 'b-teal'}`} style={{ margin: 2 }}>{i + 1}. {n}{t.states[n] === 'hidden' ? ' (ẩn)' : ''}</span>)}</div>
          <p className="small muted" style={{ marginTop: 8 }}>Sheet ghi “(ẩn)” là sheet bị ẩn sẵn trong mẫu NSW gốc; hệ thống giữ nguyên trạng thái ẩn/hiện khi xuất file.</p>
        </div>
        {readOnly ? (
        <div className="card">
          <h2>Tải mẫu NSW</h2>
          <p className="small muted">Tải về đúng file mẫu Excel NSW hệ thống đang dùng để xuất dữ liệu. Muốn thay mẫu mới, liên hệ quản trị viên.</p>
          <a className="btn" href={fileUrl('/api/admin/template/download')}>⬇ Tải mẫu đang dùng</a>
        </div>
        ) : (
        <div className="card">
          <h2>Thay mẫu NSW</h2>
          <p className="small muted">Khi NSW ban hành mẫu mới, tải file .xlsx lên đây. Hệ thống kiểm tra mẫu mới phải có đủ các sheet như mẫu hiện tại (vì dữ liệu được điền theo tên sheet và vị trí ô), rồi cập nhật lại danh mục mã từ sheet Declaration list. Mẫu cũ được cất vào thư mục sao lưu.</p>
          <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            <a className="btn" href={fileUrl('/api/admin/template/download')}>⬇ Tải mẫu đang dùng</a>
            <label className="btn primary" style={{ cursor: 'pointer' }}>{busy === -1 ? <Spinner /> : 'Tải lên mẫu mới (.xlsx)'}
              <input type="file" accept=".xlsx" style={{ display: 'none' }} onChange={(e) => { upload(e.target.files[0]); e.target.value = '' }} /></label>
            {t.custom && <button className="btn" onClick={resetTpl}>Dùng lại mẫu gốc</button>}
          </div>
          {!!t.history.length && <><h3 style={{ marginTop: 16 }}>Lịch sử thay mẫu</h3>
            {t.history.map((h, i) => <div key={i} className="small" style={{ marginBottom: 3 }}>{h.at} · <b>{h.user}</b> · {h.detail}</div>)}</>}
        </div>
        )}
      </div>

      <div className="card tight">
        <div className="card-head"><h2>Bảng ánh xạ dữ liệu → mẫu NSW</h2></div>
        <div className="scroll" style={{ maxHeight: 420 }}><table className="t"><thead><tr><th>Sheet</th><th>Ô</th><th>Nội dung</th><th>Nguồn</th></tr></thead><tbody>
          {Object.entries(s.mapping.headers).flatMap(([sh, rows]) => rows.map((r) => <tr key={sh + r.cell}><td>{sh}</td><td className="mono">{r.cell}</td><td>{r.label}</td><td className="small mono">{r.source}</td></tr>))}
          {Object.entries(s.mapping.tables).map(([sh, x]) => <tr key={sh}><td>{sh}</td><td className="mono">{x.cols.split(':')[0]}{x.first}:{x.cols.split(':')[1]}…</td><td>Danh sách – số dòng thay đổi theo chứng từ</td><td className="small mono">{x.source}{x.max_row ? ` (tối đa đến dòng ${x.max_row})` : ''}</td></tr>)}
          {Object.entries(s.mapping.clear_only).map(([sh, r]) => <tr key={sh + 'c'}><td>{sh}</td><td className="mono small">{r.join(', ')}</td><td>Chỉ xóa dữ liệu mẫu (chưa có nguồn chứng từ)</td><td className="small">—</td></tr>)}
        </tbody></table></div>
      </div>

      <div className="card" style={{ borderColor: '#f5d0fe' }}>
        <h2>Dữ liệu mẫu để kiểm thử <span className="badge b-sample">DỮ LIỆU MẪU</span></h2>
        <p className="small muted">Tạo một chuyến tàu MẪU (tàu giả lập, mã chuyến bắt đầu bằng “SAMPLE-”) với bộ chứng từ được sinh tự động. Chuyến mẫu luôn được gắn nhãn và không dùng cho khai báo thật.</p>
        <div className="grid g3">
          {[[1, 'Bộ chứng từ đầy đủ & thống nhất', 'GD, NOA, Tonnage, Manifest, 3 B/L, Crew List 22 người, DG, Stores (XLSX), Effects (DOCX)'],
            [2, 'Bộ chứng từ có sai lệch', 'Nhiều B/L, Gross Weight ≠ Manifest, sai container, ETA khác nhau, trùng hộ chiếu, B/L của tàu khác, container khai vừa rỗng vừa có hàng, Bản khai an ninh'],
            [3, 'Bộ chứng từ scan / thiếu thông tin', 'PDF scan + ảnh PNG (OCR), GD thiếu ETA và số thuyền viên, danh sách thuyền viên khó đọc, 1 chứng từ không nhận diện được'],
            [4, 'Bộ 5 chứng từ, danh sách lớn', 'GD, NOA, Tonnage, Crew List 35 người, Cargo Manifest 50 dòng – tên file không gợi ý loại chứng từ'],
            [5, 'Chứng từ gộp trong 2 file', '1 PDF gộp 8 chứng từ (GD, NOA, Tonnage, Manifest, 3 B/L, DG) + 1 Word gộp Crew List, hành lý, dự trữ → tự tách']].map(([n, ti, d]) => (
            <div key={n} className="stat"><b>Tình huống {n}: {ti}</b><div className="small muted" style={{ margin: '6px 0 10px' }}>{d}</div>
              <button className="btn sm primary" disabled={!!busy} onClick={() => sample(n)}>{busy === n ? <Spinner /> : 'Tạo chuyến mẫu'}</button></div>))}
        </div>
      </div>
    </>
  )
}

// ---------------------------------------------------------------- monitoring
function Monitor() {
  const [sub, setSub] = useState('system')
  return (
    <>
      <div className="row" style={{ gap: 6, marginBottom: 14, flexWrap: 'wrap' }}>
        {[['system', 'Trạng thái hệ thống'], ['access', 'Lịch sử truy cập'], ['activity', 'Nhật ký thao tác'], ['backup', 'Sao lưu & khôi phục']].map(([k, l]) => (
          <button key={k} className={`btn sm ${sub === k ? 'primary' : ''}`} onClick={() => setSub(k)}>{l}</button>))}
      </div>
      {sub === 'system' && <SystemStatus />}
      {sub === 'access' && <AccessLog />}
      {sub === 'activity' && <Activity />}
      {sub === 'backup' && <Backups />}
    </>
  )
}

function SystemStatus() {
  const [s, setS] = useState(null)
  useEffect(() => { api('/api/admin/system').then(setS) }, [])
  if (!s) return <div className="empty"><Spinner /></div>
  return (
    <div className="grid g2" style={{ alignItems: 'start' }}>
      <div className="card">
        <h2>Công cụ xử lý chứng từ</h2>
        <dl className="kv">
          <dt>Đọc PDF văn bản</dt><dd>{s.ocr.pdf_engine || '—'} + pdfplumber (bảng)</dd>
          <dt>OCR (scan / ảnh)</dt><dd>{s.ocr.available ? <span className="badge b-green">{s.ocr.engine} – sẵn sàng</span> : <span className="badge b-red">Chưa cài đặt</span>}</dd>
          <dt>Ngôn ngữ OCR</dt><dd>{(s.ocr.languages || []).join(', ') || '—'}</dd>
          <dt>DOCX / XLSX / CSV</dt><dd>python-docx / openpyxl</dd>
        </dl>
      </div>
      <div className="card">
        <h2>Dữ liệu hệ thống</h2>
        <dl className="kv">
          <dt>Chuyến tàu</dt><dd>{s.counts.voyages}</dd>
          <dt>Chứng từ</dt><dd>{s.counts.documents}</dd>
          <dt>File Excel đã xuất</dt><dd>{s.counts.exports}</dd>
          <dt>Phiên đăng nhập đang mở</dt><dd>{s.counts.sessions}</dd>
          <dt>Dung lượng dữ liệu</dt><dd>{fmtSize(s.data_size)}</dd>
        </dl>
      </div>
    </div>
  )
}

function AccessLog() {
  const [rows, setRows] = useState(null)
  const [users, setUsers] = useState([])
  const [f, setF] = useState({ user: '', action: '' })
  useEffect(() => { api('/api/admin/users').then(setUsers) }, [])
  useEffect(() => { setRows(null); api(`/api/admin/access?user=${encodeURIComponent(f.user)}&action=${f.action}`).then(setRows) }, [f])
  return (
    <div className="card tight">
      <div className="card-head" style={{ gap: 8, flexWrap: 'wrap' }}><h2>Lịch sử truy cập</h2>
        <div className="row" style={{ gap: 8 }}>
          <select style={{ width: 190 }} value={f.user} onChange={(e) => setF({ ...f, user: e.target.value })}><option value="">Tất cả tài khoản</option>{users.map((u) => <option key={u.id} value={u.username}>{u.username}</option>)}</select>
          <select style={{ width: 190 }} value={f.action} onChange={(e) => setF({ ...f, action: e.target.value })}><option value="">Tất cả sự kiện</option>{Object.entries(ACCESS).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}</select>
        </div></div>
      {!rows ? <div className="empty"><Spinner /></div> : (
        <div className="scroll" style={{ maxHeight: 560 }}><table className="t">
          <thead><tr><th>Thời gian</th><th>Tài khoản</th><th>Sự kiện</th><th>IP</th><th>Trình duyệt / thiết bị</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.id}><td className="small">{r.at}</td><td className="mono">{r.username}</td>
            <td><span className={`badge ${ACCESS[r.action]?.[1] || 'b-gray'}`}>{ACCESS[r.action]?.[0] || r.action}</span></td>
            <td className="small mono">{r.ip || '—'}</td><td className="small muted" style={{ maxWidth: 380, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.user_agent}>{r.user_agent || '—'}</td></tr>)}
            {!rows.length && <tr><td colSpan={5} className="empty">Chưa có lượt truy cập nào được ghi lại.</td></tr>}</tbody>
        </table></div>)}
    </div>
  )
}

function Activity() {
  const [rows, setRows] = useState(null)
  const [users, setUsers] = useState([])
  const [user, setUser] = useState('')
  useEffect(() => { api('/api/admin/users').then(setUsers) }, [])
  useEffect(() => { setRows(null); api(`/api/admin/activity?user=${encodeURIComponent(user)}`).then(setRows) }, [user])
  return (
    <div className="card tight">
      <div className="card-head"><h2>Nhật ký thao tác</h2>
        <select style={{ width: 220 }} value={user} onChange={(e) => setUser(e.target.value)}><option value="">Tất cả người thao tác</option>{users.map((u) => <option key={u.id} value={u.username}>{u.username}</option>)}</select></div>
      {!rows ? <div className="empty"><Spinner /></div> : (
        <div className="scroll" style={{ maxHeight: 560 }}><table className="t">
          <thead><tr><th>Thời gian</th><th>Người thao tác</th><th>Thao tác</th><th>Đối tượng</th><th>Chi tiết</th></tr></thead>
          <tbody>{rows.map((r, i) => <tr key={i}><td className="small">{r.at}</td><td className="mono small">{r.user || '—'}</td>
            <td><span className={`badge ${r.kind === 'admin' ? 'b-blue' : 'b-gray'}`}>{act(r.action)}</span></td>
            <td className="mono small">{r.target || '—'}</td><td className="small muted">{r.detail || '—'}</td></tr>)}
            {!rows.length && <tr><td colSpan={5} className="empty">Chưa có thao tác nào.</td></tr>}</tbody>
        </table></div>)}
    </div>
  )
}

function Backups() {
  const [d, setD] = useState(null)
  const [busy, setBusy] = useState('')
  const toast = useToast()
  const load = () => api('/api/admin/backups').then(setD)
  useEffect(() => { load() }, [])
  const make = async () => { setBusy('make'); try { const r = await api('/api/admin/backups', { method: 'POST' }); toast(`Đã sao lưu: ${r.name}`); load() } catch (e) { toast(e.message, 'err') } finally { setBusy('') } }
  const upload = async (file) => {
    if (!file) return
    const form = new FormData(); form.append('file', file)
    setBusy('up'); try { await api('/api/admin/backups/upload', { method: 'POST', form }); toast('Đã tải lên bản sao lưu'); load() } catch (e) { toast(e.message, 'err') } finally { setBusy('') }
  }
  const restore = async (b) => {
    if (!confirm(`Khôi phục toàn bộ dữ liệu về bản ${b.name}?\n\nMọi chuyến tàu, chứng từ, tài khoản sẽ trở về đúng thời điểm sao lưu. Trạng thái hiện tại được tự sao lưu trước khi khôi phục. Sau khi khôi phục bạn cần đăng nhập lại.`)) return
    setBusy(b.name)
    try { const r = await api(`/api/admin/backups/${encodeURIComponent(b.name)}/restore`, { method: 'POST' }); alert(`Đã khôi phục dữ liệu.\nTrạng thái trước khi khôi phục được lưu thành ${r.safety_backup}.`); window.location.href = '/settings' }
    catch (e) { toast(e.message, 'err') } finally { setBusy('') }
  }
  const del = async (b) => { if (!confirm(`Xóa bản sao lưu ${b.name}? Không thể hoàn tác.`)) return; try { await api(`/api/admin/backups/${encodeURIComponent(b.name)}`, { method: 'DELETE' }); toast('Đã xóa bản sao lưu'); load() } catch (e) { toast(e.message, 'err') } }
  if (!d) return <div className="empty"><Spinner /></div>
  return (
    <>
      <div className="card">
        <h2>Sao lưu & khôi phục</h2>
        <p className="small muted">Bản sao lưu gồm toàn bộ cơ sở dữ liệu (chuyến tàu, dữ liệu trích xuất, tài khoản, nhật ký), các chứng từ đã tải lên, các file Excel đã xuất và mẫu NSW đang dùng. Nên tải bản sao lưu về máy để cất giữ ở nơi khác.</p>
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          <button className="btn primary" disabled={!!busy} onClick={make}>{busy === 'make' ? <Spinner /> : 'Sao lưu ngay'}</button>
          <label className="btn" style={{ cursor: 'pointer' }}>{busy === 'up' ? <Spinner /> : 'Tải lên bản sao lưu (.zip)'}
            <input type="file" accept=".zip" style={{ display: 'none' }} onChange={(e) => { upload(e.target.files[0]); e.target.value = '' }} /></label>
        </div>
      </div>
      <div className="card tight">
        <div className="card-head"><h2>Các bản sao lưu ({d.backups.length})</h2></div>
        <table className="t">
          <thead><tr><th>Tên bản sao lưu</th><th>Thời gian</th><th>Dung lượng</th><th style={{ textAlign: 'right' }}>Thao tác</th></tr></thead>
          <tbody>{d.backups.map((b) => <tr key={b.name}><td className="mono small">{b.name}</td><td className="small">{b.created_at}</td><td className="small">{fmtSize(b.size)}</td>
            <td style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
              <a className="btn sm" href={fileUrl(`/api/admin/backups/${encodeURIComponent(b.name)}/download`)}>⬇ Tải về</a>{' '}
              <button className="btn sm primary" disabled={!!busy} onClick={() => restore(b)}>{busy === b.name ? <Spinner /> : 'Khôi phục'}</button>{' '}
              <button className="btn sm danger" onClick={() => del(b)}>Xóa</button></td></tr>)}
            {!d.backups.length && <tr><td colSpan={4} className="empty">Chưa có bản sao lưu nào. Bấm “Sao lưu ngay” để tạo.</td></tr>}</tbody>
        </table>
      </div>
      {!!d.history.length && <div className="card"><h2>Lịch sử sao lưu & khôi phục</h2>
        {d.history.map((h, i) => <div key={i} className="small" style={{ marginBottom: 4 }}>{h.at} · <b>{h.user}</b> · {act(h.action)} · <span className="mono">{h.target}</span>{h.detail ? <span className="muted"> – {h.detail}</span> : null}</div>)}</div>}
    </>
  )
}

// ---------------------------------------------------------------- statistics
function Stats() {
  const [days, setDays] = useState(30)
  const [d, setD] = useState(null)
  useEffect(() => { setD(null); api(`/api/admin/stats?days=${days}`).then(setD) }, [days])
  return (
    <>
      <div className="row" style={{ gap: 6, marginBottom: 14 }}>
        {[[7, '7 ngày'], [30, '30 ngày'], [90, '90 ngày'], [365, '12 tháng']].map(([n, l]) => <button key={n} className={`btn sm ${days === n ? 'primary' : ''}`} onClick={() => setDays(n)}>{l}</button>)}
        {d && <span className="small muted" style={{ marginLeft: 8 }}>Từ {d.since} đến hôm nay</span>}
      </div>
      {!d ? <div className="empty"><Spinner /></div> : (
        <>
          <div className="grid g6" style={{ marginBottom: 18 }}>
            {[['Lượt đăng nhập', d.totals.logins], ['Đăng nhập sai', d.totals.failed, d.totals.failed ? 'red' : ''], ['Chuyến tàu tạo mới', d.totals.voyages],
              ['Chứng từ tải lên', d.totals.documents], ['Lượt chỉnh sửa / xác nhận', d.totals.edits], ['File Excel đã xuất', d.totals.exports]].map(([l, v, c]) => (
              <div key={l} className={`stat ${c || ''}`}><div className="lbl">{l}</div><div className="val">{v}</div></div>))}
          </div>
          <div className="card tight">
            <div className="card-head"><h2>Theo người dùng</h2></div>
            <div style={{ overflowX: 'auto' }}><table className="t">
              <thead><tr><th>Tài khoản</th><th>Họ tên</th><th>Vai trò</th><th>Đăng nhập</th><th>Đăng nhập sai</th><th>Chuyến tàu tạo</th><th>Chứng từ tải lên</th><th>Chỉnh sửa / xác nhận</th><th>Excel đã xuất</th><th>Hoạt động gần nhất</th></tr></thead>
              <tbody>{d.users.map((u) => <tr key={u.id}><td className="mono">{u.username}{!u.active && <span className="badge b-red" style={{ marginLeft: 4 }}>Đã khóa</span>}</td><td>{u.full_name}</td>
                <td><span className={`badge ${ROLE[u.role]?.[1]}`}>{ROLE[u.role]?.[0] || u.role}</span></td>
                <td>{u.logins}</td><td>{u.failed || '—'}</td><td>{u.voyages}</td><td>{u.documents}</td><td>{u.edits}</td><td>{u.exports}</td><td className="small">{u.last_active || '—'}</td></tr>)}</tbody>
            </table></div>
          </div>
          <div className="card tight">
            <div className="card-head"><h2>Theo ngày</h2></div>
            <div className="scroll" style={{ maxHeight: 420 }}><table className="t">
              <thead><tr><th>Ngày</th><th>Lượt đăng nhập</th><th>Chuyến tàu tạo</th><th>Chứng từ tải lên</th><th>Excel đã xuất</th></tr></thead>
              <tbody>{d.daily.map((x) => <tr key={x.date}><td>{x.date.split('-').reverse().join('/')}</td><td>{x.logins}</td><td>{x.voyages}</td><td>{x.documents}</td><td>{x.exports}</td></tr>)}
                {!d.daily.length && <tr><td colSpan={5} className="empty">Chưa có hoạt động trong khoảng thời gian này.</td></tr>}</tbody>
            </table></div>
          </div>
        </>
      )}
    </>
  )
}
