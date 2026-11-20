import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fileUrl, fmtSize } from '../api'
import { Badge, Conf, DOC_STATUS, Modal, Spinner, useToast, useVoyage, VoyageHeader } from '../components'

const ACCEPT = '.pdf,.jpg,.jpeg,.png,.tif,.tiff,.bmp,.docx,.xlsx,.xlsm,.xls,.csv,.txt'

export default function Documents() {
  const { id, voyage, reload } = useVoyage()
  const [docs, setDocs] = useState(null)
  const [types, setTypes] = useState({})
  const [over, setOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [view, setView] = useState(null)
  const [fill, setFill] = useState(false)
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
            <div className="small muted">General Declaration · Cargo Manifest · B/L · Crew List · Passenger List · DG Manifest · Notice of Arrival · Tonnage Certificate · Crew's Effects · Ship's Stores · khác</div>
          </>}
          <input ref={input} type="file" multiple accept={ACCEPT} hidden onChange={(e) => { upload([...e.target.files]); e.target.value = '' }} />
        </div>
      </div>

      <div className="card tight">
        <div className="card-head">
          <h2>Chứng từ của chuyến ({docs?.length || 0})</h2>
          <div className="row">{busy && <span className="small muted"><Spinner /> Đang xử lý…</span>}
            <button className="btn" disabled={busy || !docs?.length} onClick={() => setFill(true)}>Điền hồ sơ chuyến từ chứng từ…</button>
            <Link className="btn primary" to={`/voyages/${id}/crosscheck`}>Tiếp: Đối chiếu dữ liệu →</Link></div>
        </div>
        {!docs ? <div className="empty"><Spinner /></div> : docs.length === 0 ? <div className="empty">Chưa có chứng từ. Tải lên bộ chứng từ của chuyến tàu ở trên.</div> : (
          <table className="t">
            <thead><tr><th>Tên file</th><th>Định dạng</th><th>Dung lượng</th><th style={{ width: 290 }}>Loại chứng từ</th><th>Trạng thái</th><th>Trang · Phương pháp</th><th>Dữ liệu</th><th /></tr></thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td className="wrap-any" style={{ minWidth: 180 }}><b>{d.original_name}</b><div className="small muted">{d.uploaded_at}</div></td>
                  <td><span className="badge b-gray">{(d.ext || '').replace('.', '').toUpperCase()}</span></td>
                  <td className="small">{fmtSize(d.size)}</td>
                  <td>
                    <select value={d.doc_type || ''} disabled={d.status === 'PROCESSING'} onChange={(e) => setType(d, e.target.value)}>
                      {!d.doc_type && <option value="">— chờ nhận diện —</option>}
                      {Object.entries(types).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                    <div className="small" style={{ marginTop: 3 }}>
                      {d.doc_type_confirmed ? <span className="badge b-green">Nhân viên đã xác nhận loại</span>
                        : d.doc_type ? <span className={`badge ${d.doc_type === 'OTHER' ? 'b-amber' : 'b-blue'}`}>Tự nhận diện theo nội dung{d.doc_type_score ? ` · ${Math.round(d.doc_type_score * 100)}%` : ''}</span> : null}
                    </div>
                  </td>
                  <td><Badge map={DOC_STATUS} value={d.status} />{d.status === 'PROCESSING' && <> <Spinner /></>}
                    {d.error && <div className="small" style={{ color: 'var(--red)', maxWidth: 260 }}>{d.error}</div>}</td>
                  <td className="small">{d.page_count ?? '—'} trang<br /><span className="muted">{d.extraction_method || ''}</span>
                    {d.avg_confidence != null && <> <Conf value={d.avg_confidence} method={d.extraction_method} /></>}</td>
                  <td className="small">{d.n_fields} trường<br />{d.n_records ? <span className="muted">{d.n_records} dòng/bản ghi</span> : null}</td>
                  <td className="right" style={{ whiteSpace: 'nowrap' }}>
                    <button className="btn sm" onClick={() => setView(d)}>Xem</button>{' '}
                    <button className="btn sm" onClick={() => reprocess(d)} disabled={d.status === 'PROCESSING'} title="Đọc lại file từ đầu (dữ liệu đã sửa/xác nhận của file này sẽ bị thay thế)">Xử lý lại</button>{' '}
                    <button className="btn sm" onClick={() => replace(d)}>Thay file</button>{' '}
                    <button className="btn sm danger" onClick={() => del(d)}>Xóa</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="alert blue">Hệ thống nhận diện loại chứng từ theo <b>nội dung</b> (tiêu đề, từ khóa), không theo tên file. Nếu nhận diện sai, chọn lại loại ở cột “Loại chứng từ” – chứng từ sẽ được trích xuất lại theo loại mới.
        OCR (Tesseract) được dùng cho trang scan/ảnh; độ chính xác phụ thuộc chất lượng bản scan nên các trường có độ tin cậy thấp sẽ được đánh dấu để kiểm tra.</div>
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
          <thead><tr><th>Nhóm</th><th>Bản ghi</th><th>Trường</th><th>Giá trị gốc</th><th>Trang</th><th>Tin cậy</th></tr></thead>
          <tbody>{fields.map((f) => <tr key={f.id}><td className="small">{f.section}</td><td className="small mono">{f.record_key}</td><td>{f.field_label}</td>
            <td className="wrap-any">{f.original_value}</td><td>{f.page_no}</td><td><Conf value={f.confidence} method={f.method} /></td></tr>)}</tbody>
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
      setPick(Object.fromEntries(r.filter((x) => x.value && !x.current).map((x) => [x.key, true])))
    })
  }, [voyage.id])
  const apply = async () => {
    const body = { ...voyage }
    for (const r of rows) if (pick[r.key] && r.value) body[r.key] = r.value
    try { await api(`/api/voyages/${voyage.id}`, { method: 'PUT', body }); toast('Đã cập nhật hồ sơ chuyến tàu'); onDone() } catch (e) { toast(e.message, 'err') }
  }
  return (
    <Modal title="Điền hồ sơ chuyến tàu từ chứng từ" onClose={onClose} footer={<><button className="btn" onClick={onClose}>Hủy</button><button className="btn primary" onClick={apply}>Áp dụng mục đã chọn</button></>}>
      <p className="small muted" style={{ marginTop: 0 }}>Đề xuất lấy từ General Declaration / Notice of Arrival / Tonnage Certificate của chính chuyến này. Chỉ đề xuất khi các chứng từ ghi giống nhau; trường mâu thuẫn không được tự chọn.</p>
      {!rows ? <Spinner /> : <table className="t"><thead><tr><th /><th>Trường</th><th>Hiện tại</th><th>Đề xuất</th><th>Nguồn</th></tr></thead><tbody>
        {rows.map((r) => <tr key={r.key}>
          <td><input type="checkbox" style={{ width: 'auto' }} disabled={!r.value} checked={!!pick[r.key]} onChange={(e) => setPick({ ...pick, [r.key]: e.target.checked })} /></td>
          <td>{r.label}</td><td className="small">{r.current || <span className="faint">—</span>}</td>
          <td>{r.conflict ? <span className="badge b-red">Mâu thuẫn – xem Đối chiếu</span> : r.value || <span className="badge b-gray">Not Available in Source</span>}</td>
          <td className="small muted">{r.sources.map((s) => `${s.original_name} tr.${s.page_no}`).join(', ')}</td></tr>)}
      </tbody></table>}
    </Modal>
  )
}
