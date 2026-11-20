import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Spinner, useToast } from '../components'

export default function Settings({ user }) {
  const [s, setS] = useState(null)
  const [busy, setBusy] = useState(0)
  const [nu, setNu] = useState({ username: '', full_name: '', password: '', role: 'staff' })
  const [pw, setPw] = useState({ old_password: '', new_password: '' })
  const [vessels, setVessels] = useState([])
  const toast = useToast()
  const nav = useNavigate()
  const load = () => { api('/api/settings').then(setS); api('/api/vessels').then(setVessels) }
  useEffect(load, [])
  if (!s) return <div className="empty"><Spinner /></div>

  const sample = async (n) => {
    setBusy(n)
    try { const r = await api(`/api/samples/${n}`, { method: 'POST' }); toast(`Đã tạo chuyến DỮ LIỆU MẪU – tình huống ${n}`); nav(`/voyages/${r.voyage_id}/documents`) }
    catch (e) { toast(e.message, 'err') } finally { setBusy(0) }
  }
  const addUser = async () => { try { await api('/api/users', { method: 'POST', body: nu }); toast('Đã tạo tài khoản'); setNu({ username: '', full_name: '', password: '', role: 'staff' }); load() } catch (e) { toast(e.message, 'err') } }
  const changePw = async () => { try { await api('/api/me/password', { method: 'POST', body: pw }); toast('Đã đổi mật khẩu'); setPw({ old_password: '', new_password: '' }) } catch (e) { toast(e.message, 'err') } }

  return (
    <>
      <div className="page-head"><div><h1>Cài đặt hệ thống</h1><p>Trạng thái công cụ xử lý, cấu trúc mẫu NSW, ánh xạ dữ liệu, tài khoản và dữ liệu mẫu.</p></div></div>
      <div className="grid g2">
        <div className="card">
          <h2>Công cụ xử lý chứng từ</h2>
          <dl className="kv">
            <dt>Đọc PDF văn bản</dt><dd>{s.ocr.pdf_engine || '—'} + pdfplumber (bảng)</dd>
            <dt>OCR (scan / ảnh)</dt><dd>{s.ocr.available ? <span className="badge b-green">{s.ocr.engine} – sẵn sàng</span> : <span className="badge b-red">Chưa cài đặt</span>}</dd>
            <dt>Ngôn ngữ OCR</dt><dd>{(s.ocr.languages || []).join(', ') || '—'}</dd>
            <dt>DOCX / XLSX / CSV</dt><dd>python-docx / openpyxl</dd>
            <dt>Ngưỡng “tin cậy thấp”</dt><dd>&lt; {Math.round(s.low_confidence_threshold * 100)}%</dd>
          </dl>
          <div className="alert amber" style={{ marginTop: 12 }}>Trích xuất dựa trên quy tắc (nhãn trường, tiêu đề bảng) và OCR Tesseract. Kết quả không được coi là chính xác tuyệt đối – mọi trường phải được nhân viên xác nhận trước khi xuất.</div>
        </div>
        <div className="card">
          <h2>Mẫu Excel NSW</h2>
          <dl className="kv"><dt>File mẫu</dt><dd className="mono">{s.template.path}</dd><dt>Số sheet</dt><dd>{s.template.sheets.length}</dd>
            <dt>Danh mục mã</dt><dd className="small">{Object.entries(s.codes).map(([k, v]) => `${k}: ${v}`).join(' · ')}</dd></dl>
          <div className="small" style={{ marginTop: 10 }}>{s.template.sheets.map((n, i) => <span key={n} className={`badge ${s.template.states[n] === 'hidden' ? 'b-gray' : 'b-teal'}`} style={{ margin: 2 }}>{i + 1}. {n}{s.template.states[n] === 'hidden' ? ' (ẩn)' : ''}</span>)}</div>
        </div>
      </div>

      <div className="card" style={{ borderColor: '#f5d0fe' }}>
        <h2>Dữ liệu mẫu để kiểm thử <span className="badge b-sample">DỮ LIỆU MẪU</span></h2>
        <p className="small muted">Tạo một chuyến tàu MẪU (tàu giả lập, mã chuyến bắt đầu bằng “SAMPLE-”) với bộ chứng từ được sinh tự động. Chuyến mẫu luôn được gắn nhãn và không dùng cho khai báo thật.</p>
        <div className="grid g3">
          {[[1, 'Bộ chứng từ đầy đủ & thống nhất', 'GD, NOA, Tonnage, Manifest, 3 B/L, Crew List 22 người, DG, Stores (XLSX), Effects (DOCX)'],
            [2, 'Bộ chứng từ có sai lệch', 'Nhiều B/L, Gross Weight ≠ Manifest, sai container, ETA khác nhau, trùng hộ chiếu, B/L của tàu khác, container khai vừa rỗng vừa có hàng, Bản khai an ninh'],
            [3, 'Bộ chứng từ scan / thiếu thông tin', 'PDF scan + ảnh PNG (OCR), GD thiếu ETA và số thuyền viên, danh sách thuyền viên khó đọc, 1 chứng từ không nhận diện được'],
            [4, 'Bộ 5 chứng từ, danh sách lớn', 'GD, NOA, Tonnage, Crew List 35 người, Cargo Manifest 50 dòng – tên file không gợi ý loại chứng từ'],
            [5, 'Chứng từ gộp trong 2 file', '1 PDF gộp 8 chứng từ (GD, NOA, Tonnage, Manifest, 3 B/L, DG) + 1 Word gộp Crew List, hành lý, dự trữ → tự tách']].map(([n, t, d]) => (
            <div key={n} className="stat"><b>Tình huống {n}: {t}</b><div className="small muted" style={{ margin: '6px 0 10px' }}>{d}</div>
              <button className="btn sm primary" disabled={!!busy} onClick={() => sample(n)}>{busy === n ? <Spinner /> : 'Tạo chuyến mẫu'}</button></div>))}
        </div>
      </div>

      <div className="card tight">
        <div className="card-head"><h2>Bảng ánh xạ dữ liệu → mẫu NSW</h2></div>
        <div className="scroll" style={{ maxHeight: 420 }}><table className="t"><thead><tr><th>Sheet</th><th>Ô</th><th>Nội dung</th><th>Nguồn</th></tr></thead><tbody>
          {Object.entries(s.mapping.headers).flatMap(([sh, rows]) => rows.map((r) => <tr key={sh + r.cell}><td>{sh}</td><td className="mono">{r.cell}</td><td>{r.label}</td><td className="small mono">{r.source}</td></tr>))}
          {Object.entries(s.mapping.tables).map(([sh, t]) => <tr key={sh}><td>{sh}</td><td className="mono">{t.cols.split(':')[0]}{t.first}:{t.cols.split(':')[1]}…</td><td>Danh sách – số dòng thay đổi theo chứng từ</td><td className="small mono">{t.source}{t.max_row ? ` (tối đa đến dòng ${t.max_row})` : ''}</td></tr>)}
          {Object.entries(s.mapping.clear_only).map(([sh, r]) => <tr key={sh + 'c'}><td>{sh}</td><td className="mono small">{r.join(', ')}</td><td>Chỉ xóa dữ liệu mẫu (chưa có nguồn chứng từ)</td><td className="small">—</td></tr>)}
        </tbody></table></div>
      </div>

      <div className="grid g2">
        <div className="card">
          <h2>Tài khoản</h2>
          <table className="t"><tbody>{s.users.map((u) => <tr key={u.id}><td>{u.username}</td><td>{u.full_name}</td><td><span className={`badge ${u.role === 'supervisor' ? 'b-teal' : 'b-gray'}`}>{u.role}</span></td></tr>)}</tbody></table>
          {user.role === 'supervisor' && <><hr /><h3>Thêm tài khoản</h3><div className="grid g2">
            <input placeholder="Tên đăng nhập" value={nu.username} onChange={(e) => setNu({ ...nu, username: e.target.value })} />
            <input placeholder="Họ tên" value={nu.full_name} onChange={(e) => setNu({ ...nu, full_name: e.target.value })} />
            <input placeholder="Mật khẩu (≥ 6 ký tự)" type="password" value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} />
            <select value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value })}><option value="staff">Nhân viên</option><option value="supervisor">Supervisor (được duyệt ngoại lệ)</option></select>
          </div><button className="btn primary" style={{ marginTop: 10 }} onClick={addUser}>Thêm</button></>}
          <hr /><h3>Đổi mật khẩu của tôi</h3>
          <div className="grid g2"><input type="password" placeholder="Mật khẩu hiện tại" value={pw.old_password} onChange={(e) => setPw({ ...pw, old_password: e.target.value })} />
            <input type="password" placeholder="Mật khẩu mới" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></div>
          <button className="btn" style={{ marginTop: 10 }} onClick={changePw}>Đổi mật khẩu</button>
        </div>
        <div className="card">
          <h2>Hồ sơ tàu ({vessels.length})</h2>
          <p className="small muted">Hồ sơ tàu chỉ lưu thông tin nhận diện tàu (tên, IMO, call sign, quốc tịch), tách biệt với dữ liệu từng chuyến.</p>
          <table className="t"><thead><tr><th>Tên tàu</th><th>IMO</th><th>Call sign</th><th>Quốc tịch</th><th>Số chuyến</th></tr></thead><tbody>
            {vessels.map((v) => <tr key={v.id}><td><b>{v.vessel_name}</b></td><td>{v.imo}</td><td>{v.call_sign}</td><td>{v.flag}</td><td>{v.voyages}</td></tr>)}
            {!vessels.length && <tr><td colSpan={5} className="muted small">Chưa có. Có thể lưu hồ sơ tàu khi tạo chuyến tàu mới.</td></tr>}</tbody></table>
        </div>
      </div>
    </>
  )
}
