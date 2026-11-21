import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fileUrl, fmtSize } from '../api'
import { Badge, Conf, DOC_STATUS, FIELD_STATUS, Modal, Spinner, useToast, useVoyage, VoyageHeader } from '../components'

const ACCEPT = '.pdf,.jpg,.jpeg,.png,.tif,.tiff,.bmp,.docx,.xlsx,.xlsm,.xls,.csv,.txt'

export default function Documents() {
  const { id, voyage, reload } = useVoyage()
  const [docs, setDocs] = useState(null)
  const [types, setTypes] = useState({})
  const [over, setOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [view, setView] = useState(null)
  const [fill, setFill] = useState(false)
  const [moving, setMoving] = useState(null)
  const input = useRef()
  const toast = useToast()

  const load = useCallback(() => api(`/api/voyages/${id}/documents`).then((r) => { setDocs(r.documents); setTypes(r.types) }), [id])
  useEffect(() => { load() }, [load])
  const busy = docs?.some((d) => d.status === 'PROCESSING' || d.status === 'UPLOADED')
  useEffect(() => {
    if (!busy) { reload(); return }
    const t = setInterval(load, 2000)
    return () => clearInterval(t)
  }, [busy, load])

  const upload = async (files) => {
    if (!files.length) return
    const form = new FormData()
    for (const f of files) form.append('files', f)
    setUploading(true)
    try {
      const r = await api(`/api/voyages/${id}/documents`, { method: 'POST', form })
      for (const x of r.results) {
        if (!x.ok) toast(`Tải lên thất bại: ${x.file} – ${x.error}`, 'err')
        else if (x.warning) toast(`${x.file}: ${x.warning}`, 'warn')
      }
      const ok = r.results.filter((x) => x.ok).length
      if (ok) toast(`Đã tải lên ${ok} chứng từ – đang nhận diện và trích xuất…`)
      load()
    } catch (e) { toast(e.message, 'err') } finally { setUploading(false) }
  }
  const setType = async (d, t) => {
    try { await api(`/api/documents/${d.id}/type`, { method: 'PUT', body: { doc_type: t } }); toast('Đã cập nhật loại chứng từ – đang trích xuất lại'); load() } catch (e) { toast(e.message, 'err') }
  }
  const del = async (d) => {
    if (!window.confirm(`Xóa chứng từ "${d.original_name}" và toàn bộ dữ liệu trích xuất từ chứng từ này?`)) return
    await api(`/api/documents/${d.id}`, { method: 'DELETE' }); toast('Đã xóa chứng từ'); load()
  }
  const reprocess = async (d) => {
    const msg = d.status === 'EXTRACTED'
      ? `Đọc lại "${d.original_name}" từ đầu?\n\nToàn bộ dữ liệu đã trích xuất từ file này (kể cả các trường đã sửa / đã xác nhận) sẽ bị thay bằng kết quả đọc mới và phải xác nhận lại.`
      : `Xử lý lại "${d.original_name}"?`
    if (!window.confirm(msg)) return
    await api(`/api/documents/${d.id}/process`, { method: 'POST' }); load()
  }
  const setSplit = async (doc, split) => {
    const msg = split ? `Cho phép hệ thống tự tách "${doc.original_name}" nếu đây là file gộp nhiều chứng từ?`
      : `Hủy tách "${doc.original_name}"?\n\nCác chứng từ con (và dữ liệu đã sửa/xác nhận của chúng) sẽ bị xóa; file được xử lý lại như MỘT chứng từ.`
    if (!window.confirm(msg)) return
    try { await api(`/api/documents/${doc.id}/split`, { method: 'POST', body: { split } }); toast(split ? 'Đang tách lại file' : 'Đã hủy tách – đang xử lý như một chứng từ'); load() }
    catch (e) { toast(e.message, 'err') }
  }
  const extractAll = async () => {
    try { const r = await api(`/api/voyages/${id}/process-pending`, { method: 'POST' }); toast(r.queued ? `Đang trích xuất ${r.queued} chứng từ chưa xử lý / lỗi` : 'Không còn chứng từ nào chờ trích xuất'); load() }
    catch (e) { toast(e.message, 'err') }
  }
  const confirmBelongs = async (d) => {
    const reason = window.prompt(`Xác nhận "${d.original_name}" thuộc đúng chuyến tàu này?\nGhi lý do (VD: đã kiểm tra bản gốc, B/L ghi tên tàu cũ):`)
    if (!reason) return
    try { await api(`/api/documents/${d.id}/confirm-voyage`, { method: 'POST', body: { confirmed: true, reason } }); toast('Đã xác nhận chứng từ đúng hồ sơ'); load(); reload() }
    catch (e) { toast(e.message, 'err') }
  }
  const replace = (d) => {
    const el = document.createElement('input')
    el.type = 'file'; el.accept = ACCEPT
    el.onchange = async () => {
      const form = new FormData(); form.append('file', el.files[0])
      try { await api(`/api/documents/${d.id}/replace`, { method: 'POST', form }); toast('Đã thay file – đang xử lý lại'); load() } catch (e) { toast(e.message, 'err') }
    }
    el.click()
  }

  return (
    <>
      <VoyageHeader voyage={voyage} current="upload" />
      <div className="card">
        <div className={`drop ${over ? 'over' : ''}`} onClick={() => input.current.click()}
          onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); upload([...e.dataTransfer.files]) }}>
          {uploading ? <><Spinner /> Đang tải lên…</> : <>
            <div style={{ fontSize: 15 }}><b>Kéo thả chứng từ vào đây</b> hoặc bấm để chọn nhiều file</div>
            <div className="small muted" style={{ marginTop: 6 }}>PDF (văn bản hoặc scan), JPG/PNG/TIFF, DOCX, XLSX/XLS, CSV · tối đa 50MB/file · có thể tải nhiều chứng từ cùng loại</div>
            <div className="small muted">General Declaration · Notice of Arrival · Tonnage Certificate · Cargo Manifest · B/L · Crew List · Passenger List · DG Manifest · Crew's Effects · Ship's Stores · Ship Security · Health · Plant · Animal · Empty Container · chứng từ khác (Unknown)</div>
          </>}
          <input ref={input} type="file" multiple accept={ACCEPT} hidden onChange={(e) => { upload([...e.target.files]); e.target.value = '' }} />
        </div>
      </div>

      <div className="card tight">
        <div className="card-head">
          <h2>Chứng từ của chuyến ({docs?.length || 0})</h2>
          <div className="row">{busy && <span className="small muted"><Spinner /> Đang xử lý…</span>}
            <button className="btn" disabled={busy || !docs?.some((x) => x.status === 'UPLOADED' || x.status === 'ERROR')} onClick={extractAll}
              title="Trích xuất các chứng từ chưa xử lý hoặc bị lỗi (không đụng tới chứng từ đã trích xuất)">Trích xuất tất cả</button>
            <button className="btn" disabled={busy || !docs?.length} onClick={() => setFill(true)}>Điền hồ sơ chuyến từ chứng từ…</button>
            <Link className="btn primary" to={`/voyages/${id}/crosscheck`}>Tiếp: Đối chiếu dữ liệu →</Link></div>
        </div>
        {!docs ? <div className="empty"><Spinner /></div> : docs.length === 0 ? <div className="empty">Chưa có chứng từ. Tải lên bộ chứng từ của chuyến tàu ở trên.</div> : (
          <div style={{ overflowX: 'auto' }}><table className="t">
            <thead><tr><th>Tên file</th><th style={{ width: 220 }}>Loại chứng từ</th><th>Trạng thái</th><th>Trang · Dữ liệu</th></tr></thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td className="wrap-any" style={{ minWidth: 240, paddingLeft: d.parent_id ? 28 : undefined }}>{d.parent_id ? <span className="muted">↳ </span> : null}<b>{d.original_name}</b><div className="small muted"><span className="badge b-gray" style={{ marginRight: 6 }}>{(d.ext || '').replace('.', '').toUpperCase()}</span>{fmtSize(d.size)} · {d.uploaded_at}</div>
                  <div style={{ marginTop: 6 }}>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, justifyContent: 'flex-start' }}>
                    <button className="btn sm" onClick={() => setView(d)}>Xem</button>
                    <button className="btn sm" onClick={() => reprocess(d)} disabled={d.status === 'PROCESSING'} title="Đọc lại file từ đầu (dữ liệu đã sửa/xác nhận của file này sẽ bị thay thế)">Xử lý lại</button>
                    {!d.parent_id && <button className="btn sm" onClick={() => replace(d)}>Thay file</button>}
                    <button className="btn sm danger" onClick={() => del(d)}>Xóa</button>
                    {(d.suspect > 0 || d.status === 'EXTRACTED') && <button className="btn sm ghost" onClick={() => setMoving(d)} title="Chuyển chứng từ sang chuyến tàu khác">Chuyển chuyến…</button>}
                    </div>
                    {d.status === 'SPLIT' && <div style={{ marginTop: 4 }}><button className="btn sm ghost" onClick={() => setSplit(d, false)} title="Xử lý cả file như một chứng từ">Hủy tách</button></div>}
                    {!d.parent_id && d.split_disabled ? <div style={{ marginTop: 4 }}><button className="btn sm ghost" onClick={() => setSplit(d, true)} title="Cho phép tự tách nếu là file gộp">Tách file gộp</button></div> : null}
                    {d.suspect > 0 && !d.voyage_confirmed && <div style={{ marginTop: 4 }}><button className="btn sm" onClick={() => confirmBelongs(d)}>Xác nhận đúng hồ sơ</button></div>}
                  </div></td>
                  <td>{d.status === 'SPLIT' ? <div className="small"><b>File gộp nhiều chứng từ</b><div className="muted">{d.error}. Từng phần được nhận diện, trích xuất và đối chiếu riêng (bên dưới); số trang tính theo file gộp.</div></div> : <>
                    <select value={d.doc_type || ''} disabled={d.status === 'PROCESSING'} onChange={(e) => setType(d, e.target.value)}>
                      {!d.doc_type && <option value="">— chờ nhận diện —</option>}
                      {Object.entries(types).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                    <div className="small" style={{ marginTop: 3 }}>
                      {d.doc_type_confirmed ? <span className="badge b-green">Nhân viên đã xác nhận loại</span>
                        : d.doc_type ? <span className={`badge ${d.doc_type === 'OTHER' ? 'b-amber' : 'b-blue'}`}>Tự nhận diện theo nội dung{d.doc_type_score ? ` · ${Math.round(d.doc_type_score * 100)}%` : ''}</span> : null}
                      {d.parent_id ? <span className="badge b-teal" style={{ marginLeft: 4 }}>Tách từ file gộp</span> : null}
                    </div></>}
                  </td>
                  <td><Badge map={DOC_STATUS} value={d.status} />{d.status === 'PROCESSING' && <> <Spinner /></>}
                    {d.suspect > 0 && !d.voyage_confirmed && <div><span className="badge b-red" style={{ marginTop: 4 }} title="Tên tàu / IMO / số chuyến khác hồ sơ - dữ liệu chưa đưa vào Excel">Nghi sai hồ sơ</span></div>}
                    {d.voyage_confirmed ? <div><span className="badge b-green" style={{ marginTop: 4 }} title={`Xác nhận bởi ${d.voyage_confirmed_by}`}>Đã xác nhận đúng hồ sơ</span></div> : null}
                    {d.error && d.status !== 'SPLIT' && <div className="small" style={{ color: d.status === 'ERROR' ? 'var(--red)' : 'var(--amber)', maxWidth: 260 }}>{d.error}</div>}</td>
                  <td className="small" style={{ minWidth: 90 }}>{d.page_count ?? '—'} trang<div className="muted">{d.extraction_method || ''}</div>
                    {d.avg_confidence != null && <> <Conf value={d.avg_confidence} method={d.extraction_method} /></>}
                    <div style={{ marginTop: 3 }}>{d.n_fields} trường</div>{d.n_records ? <div className="muted">{d.n_records} dòng</div> : null}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </div>
      <div className="alert blue">Hệ thống nhận diện loại chứng từ theo <b>nội dung</b> (tiêu đề, từ khóa), không theo tên file. <b>File gộp</b> nhiều chứng từ (PDF/scan, Word, Excel) được tự tách theo tiêu đề từng chứng từ; bấm “Hủy tách” nếu không muốn tách. Nếu nhận diện sai, chọn lại loại ở cột “Loại chứng từ” – chứng từ sẽ được trích xuất lại theo loại mới.
        OCR (Tesseract) được dùng cho trang scan/ảnh; độ chính xác phụ thuộc chất lượng bản scan nên các trường có độ tin cậy thấp sẽ được đánh dấu để kiểm tra.</div>
      {moving && <MoveDocument doc={moving} currentId={id} onClose={() => setMoving(null)} onDone={() => { setMoving(null); load(); reload() }} />}
      {fill && <ProfileFill voyage={voyage} onClose={() => setFill(false)} onDone={() => { setFill(false); reload() }} />}
      {view && <DocViewer doc={view} onClose={() => setView(null)} voyageId={id} />}
    </>
  )
}

function DocViewer({ doc, onClose, voyageId }) {
  const [pages, setPages] = useState(null)
  const [fields, setFields] = useState(null)
  const [tab, setTab] = useState('fields')
  useEffect(() => {
    api(`/api/documents/${doc.id}/pages`).then(setPages)
    api(`/api/voyages/${voyageId}/fields`).then((r) => setFields(r.fields.filter((f) => f.document_id === doc.id)))
  }, [doc.id])
  return (
    <Modal wide title={doc.original_name} onClose={onClose} footer={<><a className="btn" href={fileUrl(`/api/documents/${doc.id}/file`)} target="_blank" rel="noreferrer">Mở file gốc ↗</a><button className="btn primary" onClick={onClose}>Đóng</button></>}>
      <div className="tabs">
        <button className={tab === 'fields' ? 'on' : ''} onClick={() => setTab('fields')}>Dữ liệu trích xuất<span className="cnt">{fields?.length ?? '…'}</span></button>
        <button className={tab === 'text' ? 'on' : ''} onClick={() => setTab('text')}>Nội dung đọc được (theo trang)</button>
      </div>
      {tab === 'fields' && (!fields ? <Spinner /> : fields.length === 0 ? <div className="empty">Không có trường dữ liệu nào được trích xuất.</div> : (
        <div className="scroll"><table className="t">
          <thead><tr><th>Nhóm</th><th>Bản ghi</th><th>Trường</th><th>Văn bản gốc</th><th>Giá trị chuẩn hóa</th><th>Kiểu</th><th>Đơn vị</th><th>Trang</th><th>Tin cậy</th><th>Trạng thái</th></tr></thead>
          <tbody>{fields.map((f) => <tr key={f.id} style={f.status === 'EXCLUDED' ? { opacity: 0.5 } : null}><td className="small">{f.section}</td><td className="small mono">{f.record_key}</td><td>{f.field_label}</td>
            <td className="wrap-any">{f.original_value}</td><td className="wrap-any">{f.value !== f.original_value ? f.value : <span className="faint">=</span>}</td>
            <td className="small">{f.data_type || ''}</td><td className="small">{f.unit || ''}</td><td>{f.page_no}</td>
            <td><Conf value={f.confidence} method={f.method} /></td><td><Badge map={FIELD_STATUS} value={f.status} /></td></tr>)}</tbody>
        </table></div>))}
      {tab === 'text' && (!pages ? <Spinner /> : pages.map((p) => (
        <div key={p.page_no} style={{ marginBottom: 12 }}>
          <div className="row small" style={{ marginBottom: 4 }}><b>Trang {p.page_no}</b><span className="badge b-gray">{p.method}</span><Conf value={p.confidence} method={p.method} /></div>
          <div className="pre">{p.text || '(trống)'}</div>
        </div>)))}
    </Modal>
  )
}

function ProfileFill({ voyage, onClose, onDone }) {
  const [rows, setRows] = useState(null)
  const [pick, setPick] = useState({})
  const toast = useToast()
  useEffect(() => {
    api(`/api/voyages/${voyage.id}/profile-suggestions`).then((r) => {
      setRows(r)
      setPick(Object.fromEntries(r.filter((x) => x.applicable && x.value && !x.current).map((x) => [x.key, true])))
    })
  }, [voyage.id])
  const apply = async () => {
    const body = { ...voyage }
    for (const r of rows) if (pick[r.key] && r.value && r.applicable) body[r.key] = r.value
    try { await api(`/api/voyages/${voyage.id}`, { method: 'PUT', body }); toast('Đã cập nhật hồ sơ chuyến tàu'); onDone() } catch (e) { toast(e.message, 'err') }
  }
  return (
    <Modal title="Điền hồ sơ chuyến tàu từ chứng từ" onClose={onClose} footer={<><button className="btn" onClick={onClose}>Hủy</button><button className="btn primary" onClick={apply}>Áp dụng mục đã chọn</button></>}>
      <p className="small muted" style={{ marginTop: 0 }}>Đề xuất lấy từ General Declaration / Notice of Arrival / Tonnage Certificate của chính chuyến này. Chỉ đề xuất khi các chứng từ ghi giống nhau; trường mâu thuẫn không được tự chọn.</p>
      {!rows ? <Spinner /> : <table className="t"><thead><tr><th /><th>Trường</th><th>Hiện tại</th><th>Đề xuất</th><th>Nguồn</th></tr></thead><tbody>
        {rows.map((r) => <tr key={r.key}>
          <td><input type="checkbox" style={{ width: 'auto' }} disabled={!r.value || !r.applicable} checked={!!pick[r.key]} onChange={(e) => setPick({ ...pick, [r.key]: e.target.checked })} /></td>
          <td>{r.label}</td><td className="small">{r.current || <span className="faint">—</span>}</td>
          <td>{r.conflict ? <span className="badge b-red">Mâu thuẫn – xem Đối chiếu</span> : r.value || <span className="badge b-gray">Not Available in Source</span>}</td>
          <td className="small muted">{r.sources.map((s) => `${s.original_name} tr.${s.page_no}`).join(', ')}</td></tr>)}
      </tbody></table>}
    </Modal>
  )
}

export function MoveDocument({ doc, currentId, onClose, onDone }) {
  const [list, setList] = useState(null)
  const [target, setTarget] = useState('')
  const [reason, setReason] = useState('')
  const toast = useToast()
  useEffect(() => { api('/api/voyages').then((vs) => setList(vs.filter((v) => String(v.id) !== String(currentId)))) }, [currentId])
  const move = async () => {
    try { await api(`/api/documents/${doc.id}/move`, { method: 'POST', body: { voyage_id: Number(target), reason } }); toast('Đã chuyển chứng từ sang chuyến khác'); onDone() }
    catch (e) { toast(e.message, 'err') }
  }
  return (
    <Modal title={`Chuyển "${doc.original_name}" sang chuyến khác`} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Hủy</button><button className="btn primary" disabled={!target} onClick={move}>Chuyển</button></>}>
      <p className="small muted" style={{ marginTop: 0 }}>Chứng từ cùng dữ liệu đã trích xuất sẽ chuyển sang hồ sơ được chọn (phải xác nhận lại ở hồ sơ đó). Việc chuyển được ghi vào lịch sử của cả hai chuyến.</p>
      {!list ? <Spinner /> : !list.length ? <div className="alert amber">Chưa có chuyến tàu nào khác. Hãy tạo hồ sơ chuyến tàu đúng trước.</div> : (
        <div className="field"><label className="f">Chuyến tàu đích</label>
          <select value={target} onChange={(e) => setTarget(e.target.value)}><option value="">— chọn —</option>
            {list.map((v) => <option key={v.id} value={v.id}>{v.voyage_code} · {v.vessel_name || 'chưa có tên tàu'} {v.voyage_no ? `· ${v.voyage_no}` : ''} {v.is_sample ? '(MẪU)' : ''}</option>)}
          </select></div>)}
      <div className="field"><label className="f">Lý do</label><input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="VD: B/L của tàu khác tải nhầm" /></div>
    </Modal>
  )
}
