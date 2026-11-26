import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { api } from './api'

/* ---------------------------------------------------------------- labels */
export const VOYAGE_STATUS = {
  NEW: ['Hồ sơ nháp', 'b-gray'], PROCESSING: ['Đang xử lý', 'b-blue'], IN_REVIEW: ['Cần kiểm tra', 'b-amber'],
  READY: ['Sẵn sàng xuất', 'b-green'], EXPORTED: ['Đã xuất Excel', 'b-teal'],
}
export const DOC_STATUS = {
  UPLOADED: ['Đã tải lên', 'b-gray'], PROCESSING: ['Đang xử lý', 'b-blue'], EXTRACTED: ['Đã trích xuất', 'b-green'], ERROR: ['Lỗi xử lý', 'b-red'], SPLIT: ['File gộp – đã tách', 'b-teal'],
}
export const CHECK_STATUS = {
  PASSED: ['Passed – Phù hợp', 'b-green'], MISMATCH: ['Mismatch – Sai lệch', 'b-red'], MISSING_INFO: ['Missing Information – Thiếu', 'b-amber'],
  NEEDS_REVIEW: ['Needs Review – Cần kiểm tra', 'b-amber'], DUPLICATE: ['Duplicate – Trùng lặp', 'b-red'],
  LOW_CONFIDENCE: ['Low Confidence – Tin cậy thấp', 'b-amber'], WRONG_VOYAGE: ['Possible Wrong Voyage Document', 'b-red'],
  SINGLE_SOURCE: ['1 nguồn – đã lấy dữ liệu', 'b-teal'], NOT_AVAILABLE: ['Not Available in Source', 'b-gray'], NOT_ENOUGH_DATA: ['Not Enough Data', 'b-gray'],
}
export const FIELD_STATUS = { EXTRACTED: ['Chưa xác nhận', 'b-gray'], EDITED: ['Đã sửa – chưa xác nhận', 'b-amber'], CONFIRMED: ['Đã xác nhận', 'b-green'], EXCLUDED: ['Đã loại bỏ', 'b-gray'] }

export function Badge({ map, value, children }) {
  const [label, cls] = (map && map[value]) || [value, 'b-gray']
  return <span className={`badge ${cls}`}>{children || label}</span>
}

export function Conf({ value, method }) {
  if (value === null || value === undefined) return <span className="badge b-gray" title="Nhập tay">Nhập tay</span>
  const p = Math.round(value * 100)
  const cls = p >= 90 ? 'b-green' : p >= 80 ? 'b-teal' : 'b-amber'
  return <span className={`badge ${cls}`} title={`Phương pháp: ${method || ''}`}>{p}%</span>
}

export function Progress({ value }) {
  return <div className="row" style={{ gap: 8, flexWrap: 'nowrap' }}><div className="pbar" style={{ flex: 1 }}><div style={{ width: `${value}%` }} /></div><span className="small muted">{value}%</span></div>
}

export function Spinner() { return <span className="spin" /> }

/* ---------------------------------------------------------------- toasts */
const ToastCtx = createContext(() => {})
export function ToastProvider({ children }) {
  const [items, setItems] = useState([])
  const push = useCallback((msg, kind = 'ok') => {
    const id = Math.random()
    setItems((x) => [...x, { id, msg, kind }])
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === 'err' ? 7000 : 4000)
  }, [])
  return <ToastCtx.Provider value={push}>{children}<div className="toasts">{items.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.msg}</div>)}</div></ToastCtx.Provider>
}
export const useToast = () => useContext(ToastCtx)

/* ---------------------------------------------------------------- modal */
export function Modal({ title, onClose, children, footer, wide }) {
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div className={`modal ${wide ? 'wide' : ''}`}>
        <div className="mh"><h2 style={{ margin: 0 }}>{title}</h2><button className="btn ghost sm" onClick={onClose}>✕</button></div>
        <div className="mb">{children}</div>
        {footer && <div className="mf">{footer}</div>}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- voyage context */
export const WORK_STEPS = [
  { key: 'upload', path: 'documents', label: 'Tải & xử lý chứng từ' },
  { key: 'check', path: 'crosscheck', label: 'Đối chiếu dữ liệu' },
  { key: 'review', path: 'review', label: 'Kiểm tra & xác nhận' },
  { key: 'export', path: 'export', label: 'Xuất Excel NSW' },
]

export function useVoyage(poll = 0) {
  const { id } = useParams()
  const [voyage, setVoyage] = useState(null)
  const [err, setErr] = useState(null)
  const load = useCallback(() => api(`/api/voyages/${id}`).then(setVoyage).catch(setErr), [id])
  useEffect(() => { load() }, [load])
  useEffect(() => { if (!poll) return; const t = setInterval(load, poll); return () => clearInterval(t) }, [load, poll])
  return { id, voyage, reload: load, err }
}

const STEP_EN = { upload: 'Uploaded', classify: 'Classified', extract: 'Extracted', check: 'Cross-checked', review: 'Reviewed',
  ready: 'Ready to Export', export: 'Exported' }

export function VoyageHeader({ voyage, current }) {
  if (!voyage) return null
  const p = voyage.progress
  const stepDone = Object.fromEntries(p.steps.map((s) => [s.key, s.done]))
  return (
    <>
      <div className="page-head">
        <div>
          <div className="row" style={{ gap: 8 }}>
            <h1>{voyage.vessel_name || 'Chưa có tên tàu'}{voyage.voyage_no ? ` – Chuyến ${voyage.voyage_no}` : ''}</h1>
            {voyage.is_sample ? <span className="badge b-sample">DỮ LIỆU MẪU</span> : null}
            <Badge map={VOYAGE_STATUS} value={p.status} />
          </div>
          <p>Mã chuyến: <b className="mono">{voyage.voyage_code}</b> · IMO {voyage.imo || '—'} · ETA {voyage.eta || '—'} · Cảng đến {voyage.port_of_arrival || '—'}
            {' · '}<Link to={`/voyages/${voyage.id}/edit`}>Sửa thông tin chuyến</Link></p>
        </div>
        <div style={{ width: 220 }}><div className="small muted" style={{ marginBottom: 4 }}>Tiến độ xử lý</div><Progress value={p.progress} /></div>
      </div>
      <div className="stepper">
        {WORK_STEPS.map((s, i) => (
          <Link key={s.key} to={`/voyages/${voyage.id}/${s.path}`} className={`${stepDone[s.key] ? 'done' : ''} ${current === s.key ? 'cur' : ''}`}
            title={stepDone[s.key] ? 'Đã hoàn thành' : p.steps.find((x) => x.key === s.key)?.why}>
            <span className="dot">{stepDone[s.key] ? '✓' : i + 1}</span>{s.label}
          </Link>
        ))}
      </div>
      <div className="row small" style={{ gap: 6, margin: '-8px 0 14px' }}>
        <span className="muted">Trạng thái:</span>
        {p.steps.filter((s) => s.key !== 'create').map((s) => (
          <span key={s.key} className={`badge ${s.done ? 'b-teal' : 'b-gray'}`} title={s.done ? 'Đã hoàn thành' : s.why}>{s.done ? '✓ ' : ''}{STEP_EN[s.key] || s.label}</span>
        ))}
      </div>
    </>
  )
}

/* Pages in the sidebar that need a voyage: continue the voyage being worked on; a finished voyage (Excel exported)
   is not reopened here - the page stays empty and says to create / open a voyage. */
const STEP_NAMES = { documents: 'xử lý chứng từ', crosscheck: 'đối chiếu dữ liệu', review: 'kiểm tra và xác nhận', export: 'xuất file Excel NSW' }
// The voyage being worked on from the sidebar: set only when a new voyage is created, kept for this login session.
export const workVoyage = {
  get() { try { return sessionStorage.getItem('sgcl.workVoyage') } catch { return null } },
  set(id) { try { sessionStorage.setItem('sgcl.workVoyage', String(id)) } catch { /* */ } },
  clear() { try { sessionStorage.removeItem('sgcl.workVoyage'); localStorage.removeItem('sgcl.voyage') } catch { /* */ } },
}

export function VoyageGate({ target }) {
  const nav = useNavigate()
  const loc = useLocation()
  const [ready, setReady] = useState(false)
  useEffect(() => {
    // Only a voyage created in this login session ("Tạo chuyến tàu mới") is continued from the sidebar.
    // Older or sample voyages are opened from "Quản lý chuyến tàu".
    const last = workVoyage.get()
    if (!last) { setReady(true); return }
    api('/api/voyages').then((vs) => {
      const v = vs.find((x) => String(x.id) === last)
      if (v && v.progress.status !== 'EXPORTED' && !loc.state?.choose) nav(`/voyages/${last}/${target}`, { replace: true })
      else { workVoyage.clear(); setReady(true) }   // finished (or deleted): its work session is over
    }).catch(() => setReady(true))
  }, [target])
  if (!ready) return <div className="empty"><Spinner /></div>
  return (
    <div className="card" style={{ textAlign: 'center', padding: '48px 24px' }}>
      <h2 style={{ marginTop: 0 }}>Chưa có chuyến tàu đang xử lý</h2>
      <p className="muted" style={{ maxWidth: 620, margin: '8px auto 20px' }}>
        Bấm <b>Tạo chuyến tàu mới</b> để bắt đầu {STEP_NAMES[target] || 'xử lý'} cho chuyến tàu mới.
        Muốn xem, chỉnh sửa hoặc bổ sung một chuyến tàu đã làm, vào <b>Quản lý chuyến tàu</b> và bấm <b>Mở</b>.
      </p>
      <div className="row" style={{ justifyContent: 'center' }}>
        <Link className="btn primary" to="/voyages/new">+ Tạo chuyến tàu mới</Link>
        <Link className="btn" to="/voyages">Quản lý chuyến tàu</Link>
      </div>
    </div>
  )
}

export function DocLink({ id, name, page }) {
  if (!id) return <span className="muted">{name || 'Hồ sơ chuyến tàu'}</span>
  return <span>{name}{page ? <span className="muted"> · tr.{page}</span> : null}</span>
}
