import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Badge, CHECK_STATUS, Modal, Spinner, useToast, useVoyage, VoyageHeader } from '../components'
import { MoveDocument } from './Documents'

const ORDER = ['WRONG_VOYAGE', 'MISMATCH', 'DUPLICATE', 'MISSING_INFO', 'NEEDS_REVIEW', 'LOW_CONFIDENCE', 'NOT_ENOUGH_DATA', 'NOT_AVAILABLE', 'PASSED']

export default function CrossCheck() {
  const { id, voyage, reload } = useVoyage()
  const [data, setData] = useState(null)
  const [running, setRunning] = useState(false)
  const [filter, setFilter] = useState('issues')
  const [act, setAct] = useState(null)
  const toast = useToast()
  const load = useCallback(() => api(`/api/voyages/${id}/crosscheck`).then(setData), [id])
  useEffect(() => { load() }, [load])

  const run = async () => {
    setRunning(true)
    try { setData(await api(`/api/voyages/${id}/crosscheck`, { method: 'POST' })); toast('Đã chạy đối chiếu'); reload() } catch (e) { toast(e.message, 'err') } finally { setRunning(false) }
  }
  if (!data) return <><VoyageHeader voyage={voyage} current="check" /><div className="empty"><Spinner /></div></>
  const counts = {}
  for (const r of data.results) counts[r.status] = (counts[r.status] || 0) + 1
  const shown = data.results.filter((r) => filter === 'all' ? true : filter === 'issues' ? !['PASSED', 'NOT_AVAILABLE', 'NOT_ENOUGH_DATA'].includes(r.status) : r.status === filter)
  const groups = {}
  for (const r of shown) (groups[r.group_name] = groups[r.group_name] || []).push(r)
  for (const g of Object.values(groups)) g.sort((a, b) => b.blocking - a.blocking || ORDER.indexOf(a.status) - ORDER.indexOf(b.status))
  const blocking = data.results.filter((r) => r.blocking).length

  return (
    <>
      <VoyageHeader voyage={voyage} current="check" />
      <div className="card">
        <div className="row">
          <button className="btn primary" onClick={run} disabled={running}>{running ? <><Spinner /> Đang đối chiếu…</> : data.run ? 'Chạy lại đối chiếu' : 'Chạy đối chiếu'}</button>
          {data.run && <span className="small muted">Lần chạy gần nhất: {data.run.run_at} bởi {data.run.run_by}</span>}
          <div className="spacer" />
          <Link className="btn" to={`/voyages/${id}/review`}>Tiếp: Kiểm tra & xác nhận →</Link>
        </div>
        {data.run && !data.fresh && <div className="alert amber" style={{ marginTop: 12, marginBottom: 0 }}>Dữ liệu đã thay đổi sau lần đối chiếu gần nhất – hãy chạy lại đối chiếu.</div>}
        {!data.run && <div className="alert blue" style={{ marginTop: 12, marginBottom: 0 }}>Chưa chạy đối chiếu cho chuyến này. Hãy đảm bảo tất cả chứng từ đã được trích xuất, sau đó bấm “Chạy đối chiếu”.</div>}
      </div>
      {data.run && <>
        <div className="row" style={{ marginBottom: 12 }}>
          <button className={`btn sm ${filter === 'issues' ? 'primary' : ''}`} onClick={() => setFilter('issues')}>Cần xử lý ({data.results.filter((r) => !['PASSED', 'NOT_AVAILABLE', 'NOT_ENOUGH_DATA'].includes(r.status)).length})</button>
          <button className={`btn sm ${filter === 'all' ? 'primary' : ''}`} onClick={() => setFilter('all')}>Tất cả ({data.results.length})</button>
          {ORDER.filter((s) => counts[s]).map((s) => <button key={s} className={`btn sm ${filter === s ? 'primary' : ''}`} onClick={() => setFilter(s)}><Badge map={CHECK_STATUS} value={s} /> {counts[s]}</button>)}
        </div>
        {blocking > 0 ? <div className="alert red"><b>{blocking} vấn đề nghiêm trọng</b> đang chặn việc xuất file Excel (Mismatch / Duplicate / Wrong Voyage chưa được xử lý). Hệ thống không tự chọn giá trị đúng – nhân viên cần kiểm tra bản gốc và quyết định.</div>
          : <div className="alert green">Không còn vấn đề nghiêm trọng chặn xuất file. Lưu ý: “Passed” chỉ áp dụng cho trường đã được so sánh giữa ít nhất 2 chứng từ.</div>}
        {Object.keys(groups).sort().map((g) => (
          <div key={g} className="card tight">
            <div className="card-head"><h2>{g}</h2><span className="small muted">{groups[g].length} kết quả</span></div>
            <table className="t">
              <thead><tr><th style={{ width: 200 }}>Kết quả</th><th>Nội dung</th><th style={{ width: '22%' }}>Chứng từ 1</th><th style={{ width: '22%' }}>Chứng từ 2</th><th /></tr></thead>
              <tbody>{groups[g].map((r) => (
                <tr key={r.id}>
                  <td><Badge map={CHECK_STATUS} value={r.status} />{r.blocking ? <div><span className="badge b-red" style={{ marginTop: 4 }}>Chặn xuất file</span></div> : null}
                    {r.acknowledged ? <div><span className="badge b-teal" style={{ marginTop: 4 }}>Đã chấp nhận khác biệt</span></div> : null}</td>
                  <td>{r.field_key && <div className="small muted">Trường: <b>{r.field_label}</b></div>}{r.message}
                    {r.suggestion && <div className="small" style={{ color: 'var(--teal-700)', marginTop: 3 }}>→ {r.suggestion}</div>}
                    {r.ack_note && <div className="small muted">Ghi chú: {r.ack_note}</div>}</td>
                  <td className="wrap-any">{(r.value1 != null || r.doc1_id) && <><div className="mono">{r.value1 || <span className="faint">(trống)</span>}</div>
                    <div className="small muted">{r.doc1_name || 'Hồ sơ chuyến tàu'}{r.page1 ? ` · trang ${r.page1}` : ''}</div></>}</td>
                  <td className="wrap-any">{(r.value2 != null || r.doc2_id) && <><div className="mono">{r.value2 || <span className="faint">(trống)</span>}</div>
                    <div className="small muted">{r.doc2_name || (r.doc2_id ? '' : r.value2 != null ? 'Hồ sơ chuyến / số dòng đếm được' : '')}{r.page2 ? ` · trang ${r.page2}` : ''}</div></>}</td>
                  <td className="right">{['MISMATCH', 'WRONG_VOYAGE', 'DUPLICATE', 'NEEDS_REVIEW', 'MISSING_INFO'].includes(r.status) && !r.acknowledged &&
                    <button className="btn sm" onClick={() => setAct(r)}>Xử lý…</button>}</td>
                </tr>))}
              </tbody>
            </table>
          </div>
        ))}
        {!shown.length && <div className="card empty">Không có kết quả trong bộ lọc này.</div>}
      </>}
      {act && <ResolveModal r={act} voyageId={id} onClose={() => setAct(null)} onDone={() => { setAct(null); load(); reload() }} />}
    </>
  )
}

function ResolveModal({ r, voyageId, onClose, onDone }) {
  const [custom, setCustom] = useState('')
  const [note, setNote] = useState('')
  const toast = useToast()
  const canFix = r.field1_id || r.field2_id
  const resolve = async (action) => {
    try {
      await api(`/api/crosscheck/${r.id}/resolve`, { method: 'POST', body: { action, value: custom, note } })
      toast('Đã cập nhật giá trị (giá trị gốc vẫn được lưu) và chạy lại đối chiếu'); onDone()
    } catch (e) { toast(e.message, 'err') }
  }
  const [moving, setMoving] = useState(false)
  const confirmDoc = async () => {
    try { await api(`/api/documents/${r.doc1_id}/confirm-voyage`, { method: 'POST', body: { confirmed: true, reason: note } }); toast('Đã xác nhận chứng từ đúng hồ sơ và chạy lại đối chiếu'); onDone() }
    catch (e) { toast(e.message, 'err') }
  }
  const ack = async () => {
    try { await api(`/api/crosscheck/${r.id}/ack`, { method: 'POST', body: { note } }); toast('Đã ghi nhận chấp nhận khác biệt'); onDone() } catch (e) { toast(e.message, 'err') }
  }
  return (
    <Modal title="Xử lý kết quả đối chiếu" onClose={onClose}>
      <p style={{ marginTop: 0 }}><Badge map={CHECK_STATUS} value={r.status} /> {r.message}</p>
      <div className="diff" style={{ marginBottom: 14 }}>
        <div><div className="small muted">{r.doc1_name || 'Hồ sơ chuyến tàu'}{r.page1 ? ` · trang ${r.page1}` : ''}</div><div className="v">{r.value1 || '(trống)'}</div></div>
        <div><div className="small muted">{r.doc2_name || 'Nguồn so sánh'}{r.page2 ? ` · trang ${r.page2}` : ''}</div><div className="v">{r.value2 || '(trống)'}</div></div>
      </div>
      <div className="field"><label className="f">Ghi chú / lý do (lưu vào lịch sử)</label><input value={note} onChange={(e) => setNote(e.target.value)} placeholder="VD: Đã kiểm tra với bản gốc B/L do hãng tàu cung cấp" /></div>
      {canFix && r.status !== 'WRONG_VOYAGE' && <>
        <h3>Chọn giá trị đúng sau khi kiểm tra bản gốc</h3>
        <div className="row" style={{ marginBottom: 10 }}>
          {r.value1 && r.field2_id && <button className="btn" onClick={() => resolve('use1')}>Dùng giá trị chứng từ 1</button>}
          {r.value2 && r.field1_id && r.field2_id && <button className="btn" onClick={() => resolve('use2')}>Dùng giá trị chứng từ 2</button>}
        </div>
        <div className="row"><input value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="Hoặc nhập giá trị đúng khác" style={{ flex: 1 }} />
          <button className="btn" disabled={!custom.trim()} onClick={() => resolve('custom')}>Áp dụng</button></div>
        <hr />
      </>}
      {r.status === 'WRONG_VOYAGE' && r.doc1_id && <>
        <h3>Chứng từ nghi thuộc chuyến khác</h3>
        <p className="small muted" style={{ marginTop: 0 }}>Dữ liệu của chứng từ này đang KHÔNG được đưa vào file Excel. Sau khi kiểm tra bản gốc:</p>
        <div className="row" style={{ marginBottom: 12 }}>
          <button className="btn" disabled={!note.trim()} onClick={confirmDoc} title="Cần ghi lý do ở ô Ghi chú">Xác nhận đúng hồ sơ</button>
          <button className="btn" onClick={() => setMoving(true)}>Chuyển sang chuyến khác…</button>
          <Link className="btn ghost" to={`/voyages/${voyageId}/documents`}>Xóa ở màn hình Xử lý chứng từ</Link>
        </div>
        {moving && <MoveDocument doc={{ id: r.doc1_id, original_name: r.doc1_name }} currentId={voyageId} onClose={() => setMoving(false)} onDone={onDone} />}
        <hr />
      </>}
      <h3>Hoặc chấp nhận khác biệt</h3>
      <p className="small muted">Dùng khi hai chứng từ thể hiện phạm vi/cách tính khác nhau một cách hợp lệ. Giá trị của cả hai chứng từ giữ nguyên. Bắt buộc ghi lý do.</p>
      <button className="btn" disabled={!note.trim()} onClick={ack}>Chấp nhận khác biệt</button>
    </Modal>
  )
}
