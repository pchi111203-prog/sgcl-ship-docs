import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { Badge, Progress, Spinner, useToast, VOYAGE_STATUS } from '../components'

export function VoyageList({ user }) {
  const [list, setList] = useState(null)
  const [q, setQ] = useState('')
  const [showSample, setShowSample] = useState(true)
  const nav = useNavigate()
  const toast = useToast()
  const load = () => api('/api/voyages').then(setList)
  useEffect(() => { load() }, [])
  if (!list) return <div className="empty"><Spinner /></div>
  const k = q.trim().toUpperCase()
  const rows = list.filter((v) => (showSample || !v.is_sample) && (!k || [v.voyage_code, v.vessel_name, v.imo, v.voyage_no, v.call_sign].some((x) => (x || '').toUpperCase().includes(k))))
  const del = async (v) => {
    if (!window.confirm(`Xóa chuyến ${v.voyage_code} cùng toàn bộ chứng từ, dữ liệu và file đã xuất? Không thể hoàn tác.`)) return
    try { await api(`/api/voyages/${v.id}`, { method: 'DELETE' }); toast('Đã xóa chuyến tàu'); load() } catch (e) { toast(e.message, 'err') }
  }
  return (
    <>
      <div className="page-head">
        <div><h1>Quản lý chuyến tàu</h1><p>Mỗi chuyến tàu là một hồ sơ độc lập theo Mã chuyến (Voyage ID). Hồ sơ mới tạo là <b>hồ sơ nháp</b> cho tới khi tải chứng từ. Hệ thống cảnh báo khi trùng IMO/tên tàu + số chuyến + cảng đến + ETA.</p></div>
        <Link to="/voyages/new" className="btn primary">+ Tạo chuyến tàu mới</Link>
      </div>
      <div className="card tight">
        <div className="card-head">
          <input placeholder="Tìm theo mã chuyến, tên tàu, IMO, voyage no., call sign…" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 420 }} />
          <label className="row small"><input type="checkbox" checked={showSample} onChange={(e) => setShowSample(e.target.checked)} style={{ width: 'auto' }} /> Hiện chuyến dữ liệu mẫu</label>
        </div>
        <table className="t">
          <thead><tr><th>Mã chuyến</th><th>Tên tàu</th><th>IMO</th><th>Call sign</th><th>Voyage</th><th>Cảng rời cuối → Cảng đến</th><th>ETA</th><th>Chứng từ</th><th>Trạng thái</th><th style={{ width: 130 }}>Tiến độ</th><th /></tr></thead>
          <tbody>
            {rows.map((v) => (
              <tr key={v.id}>
                <td className="mono"><Link to={`/voyages/${v.id}/documents`}>{v.voyage_code}</Link></td>
                <td><b>{v.vessel_name || '—'}</b> {v.is_sample ? <span className="badge b-sample">MẪU</span> : null}</td>
                <td>{v.imo || '—'}</td><td>{v.call_sign || '—'}</td><td>{v.voyage_no || '—'}</td>
                <td className="small">{v.last_port || '—'} → {v.port_of_arrival || '—'}</td><td className="small">{v.eta || '—'}</td>
                <td>{v.progress.documents}</td><td><Badge map={VOYAGE_STATUS} value={v.progress.status} /></td>
                <td title={v.progress.steps.filter((s) => !s.done).map((s) => `${s.label}: ${s.why}`).join('\n') || 'Hoàn thành'}><Progress value={v.progress.progress} /></td>
                <td className="right" style={{ whiteSpace: 'nowrap' }}>
                  <button className="btn sm" onClick={() => nav(`/voyages/${v.id}/edit`)}>Sửa</button>{' '}
                  <button className="btn sm primary" onClick={() => nav(`/voyages/${v.id}/documents`)}>Mở</button>{' '}
                  {user.role === 'supervisor' && <button className="btn sm danger" onClick={() => del(v)}>Xóa</button>}
                </td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={11} className="empty">Không có chuyến tàu phù hợp.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  )
}

const EMPTY = { vessel_profile_id: null, vessel_name: '', imo: '', call_sign: '', flag: '', voyage_no: '', port_of_arrival: '', last_port: '', next_port: '', eta: '', etd: '', cargo_type: '', notes: '', save_profile: false }

export function VoyageForm() {
  const { id } = useParams()
  const nav = useNavigate()
  const toast = useToast()
  const [f, setF] = useState(EMPTY)  // new voyage always starts empty
  const [profiles, setProfiles] = useState([])
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(!id)
  useEffect(() => {
    api('/api/vessels').then(setProfiles)
    if (id) api(`/api/voyages/${id}`).then((v) => { setF({ ...EMPTY, ...Object.fromEntries(Object.entries(v).map(([k, x]) => [k, x ?? ''])) }); setLoaded(true) })
    else setF(EMPTY)
  }, [id])
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const pickProfile = (pid) => {
    const p = profiles.find((x) => String(x.id) === pid)
    if (!p) { setF({ ...f, vessel_profile_id: null }); return }
    // Only the vessel identity comes from the profile - never data of a previous voyage.
    setF({ ...f, vessel_profile_id: p.id, vessel_name: p.vessel_name, imo: p.imo || '', call_sign: p.call_sign || '', flag: p.flag || '' })
  }
  const save = async (e) => {
    e.preventDefault()
    setBusy(true)
    const body = { ...f, vessel_profile_id: f.vessel_profile_id || null }
    try {
      let v
      try {
        v = id ? await api(`/api/voyages/${id}`, { method: 'PUT', body }) : await api('/api/voyages', { method: 'POST', body })
      } catch (ex) {
        if (ex.status !== 409 || !ex.detail?.duplicate_id) throw ex
        if (window.confirm(`${ex.detail.message}\n\nOK = vẫn tạo hồ sơ MỚI (chuyến khác)\nCancel = mở hồ sơ ${ex.detail.duplicate_code}`)) {
          v = await api('/api/voyages', { method: 'POST', body: { ...body, allow_duplicate: true } })
        } else { nav(`/voyages/${ex.detail.duplicate_id}/documents`); return }
      }
      toast(id ? 'Đã lưu thông tin chuyến tàu' : `Đã tạo chuyến ${v.voyage_code}`)
      nav(`/voyages/${v.id}/documents`)
    } catch (ex) { toast(ex.message, 'err') } finally { setBusy(false) }
  }
  if (!loaded) return <div className="empty"><Spinner /></div>
  const inp = (k, label, ph, req) => <div className="field"><label className={`f ${req ? 'req' : ''}`}>{label}</label><input value={f[k] || ''} onChange={set(k)} placeholder={ph} /></div>
  return (
    <form onSubmit={save}>
      <div className="page-head">
        <div><h1>{id ? `Sửa chuyến tàu ${f.voyage_code || ''}` : 'Tạo chuyến tàu mới'}</h1>
          <p>{id ? 'Thay đổi được ghi vào lịch sử xử lý.' : 'Chuyến tàu mới bắt đầu với dữ liệu trống. Thông tin chi tiết sẽ được trích xuất từ chứng từ ở bước sau.'}</p></div>
        <div className="row"><button type="button" className="btn" onClick={() => nav(-1)}>Hủy</button><button className="btn primary" disabled={busy}>{id ? 'Lưu thay đổi' : 'Tạo chuyến tàu'}</button></div>
      </div>
      <div className="grid g2">
        <div className="card">
          <h2>Thông tin tàu</h2>
          {!id && profiles.length > 0 && (
            <div className="field"><label className="f">Chọn từ Hồ sơ tàu (tùy chọn)</label>
              <select value={f.vessel_profile_id || ''} onChange={(e) => pickProfile(e.target.value)}>
                <option value="">— Không dùng hồ sơ tàu —</option>
                {profiles.map((p) => <option key={p.id} value={p.id}>{p.vessel_name} {p.imo ? `· IMO ${p.imo}` : ''}</option>)}
              </select>
              <div className="hint">Chỉ điền Tên tàu / IMO / Call sign / Quốc tịch. Không lấy dữ liệu của chuyến trước.</div></div>
          )}
          {inp('vessel_name', 'Vessel Name – Tên tàu', 'VD: MV ...')}
          <div className="grid g2">{inp('imo', 'IMO Number', '7 chữ số')}{inp('call_sign', 'Call Sign')}</div>
          {inp('flag', 'Flag – Quốc tịch tàu')}
          {!id && !f.vessel_profile_id && <label className="row small"><input type="checkbox" style={{ width: 'auto' }} checked={f.save_profile} onChange={(e) => setF({ ...f, save_profile: e.target.checked })} /> Lưu thành Hồ sơ tàu để dùng cho các chuyến sau</label>}
        </div>
        <div className="card">
          <h2>Thông tin chuyến</h2>
          <div className="grid g2">{inp('voyage_no', 'Voyage Number')}{inp('cargo_type', 'Cargo Type – Loại hàng')}</div>
          <div className="grid g3">{inp('last_port', 'Last Port – Cảng rời cuối')}{inp('port_of_arrival', 'Cảng đến')}{inp('next_port', 'Next Port – Cảng tiếp theo')}</div>
          <div className="grid g2">{inp('eta', 'ETA', 'dd/mm/yyyy hh:mm')}{inp('etd', 'ETD', 'dd/mm/yyyy hh:mm')}</div>
          <div className="field"><label className="f">Ghi chú</label><textarea rows={3} value={f.notes || ''} onChange={set('notes')} /></div>
        </div>
      </div>
      <div className="alert blue">Thông tin nhập ở đây là “Hồ sơ chuyến tàu” – dùng để phát hiện chứng từ thuộc tàu/chuyến khác (Wrong Voyage Document). Dữ liệu khai báo NSW được lấy từ chứng từ đã xác nhận.</div>
    </form>
  )
}
