import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Badge, CHECK_STATUS, Conf, FIELD_STATUS, Modal, Spinner, useToast, useVoyage, VoyageHeader } from '../components'

const SECTIONS = [
  { key: 'vessel', label: 'Tàu & chuyến tàu' },
  { key: 'cargo', label: 'Hàng hóa / B/L', cols: ['bl_no', 'shipper', 'consignee', 'notify', 'description', 'packages', 'package_kind', 'gross_weight', 'gross_weight_unit', 'measurement', 'container_no', 'container_type', 'seal_no', 'pol', 'pod'], always: ['container_type'] },
  { key: 'crew', label: 'Thuyền viên', cols: ['full_name', 'family_name', 'given_name', 'rank', 'nationality', 'dob', 'pob', 'gender', 'passport_no', 'passport_expiry', 'seaman_book_no'] },
  { key: 'passenger', label: 'Hành khách', cols: ['full_name', 'family_name', 'given_name', 'nationality', 'dob', 'pob', 'gender', 'passport_no', 'passport_expiry', 'port_embark', 'port_disembark', 'transit'] },
  { key: 'dg', label: 'Hàng nguy hiểm', cols: ['bl_no', 'container_no', 'seal_no', 'un_no', 'imdg_class', 'proper_shipping_name', 'packing_group', 'packages', 'gross_weight', 'stowage'] },
  { key: 'store', label: 'Dự trữ tàu', cols: ['article', 'quantity', 'unit', 'location'] },
  { key: 'effects', label: 'Hành lý thuyền viên', cols: ['full_name', 'family_name', 'given_name', 'rank', 'effects'] },
]
const BAD = ['MISMATCH', 'DUPLICATE', 'WRONG_VOYAGE']

export default function Review() {
  const { id, voyage, reload } = useVoyage()
  const [data, setData] = useState(null)
  const [tab, setTab] = useState('vessel')
  const [onlyOpen, setOnlyOpen] = useState(false)
  const [adding, setAdding] = useState(false)
  const [showLog, setShowLog] = useState(false)
  const [rerun, setRerun] = useState(false)
  const toast = useToast()
  const load = useCallback(() => api(`/api/voyages/${id}/fields`).then(setData), [id])
  useEffect(() => { load() }, [load])

  const save = async (f, value) => {
    if ((f.value || '') === value) return
    try { await api(`/api/fields/${f.id}`, { method: 'PUT', body: { value } }); toast('Đã lưu chỉnh sửa – cần xác nhận lại trường này'); load(); reload() } catch (e) { toast(e.message, 'err') }
  }
  const confirm = async (ids, yes = true) => {
    if (!ids.length) return
    await api('/api/fields/confirm', { method: 'POST', body: { ids, confirm: yes } })
    toast(yes ? `Đã xác nhận ${ids.length} trường` : 'Đã bỏ xác nhận'); load(); reload()
  }
  const runCheck = async () => {
    setRerun(true)
    try { await api(`/api/voyages/${id}/crosscheck`, { method: 'POST' }); toast('Đã chạy lại đối chiếu'); load(); reload() } catch (e) { toast(e.message, 'err') } finally { setRerun(false) }
  }

  const bySection = useMemo(() => {
    const m = {}
    for (const f of data?.fields || []) (m[f.section] = m[f.section] || []).push(f)
    return m
  }, [data])
  if (!data) return <><VoyageHeader voyage={voyage} current="review" /><div className="empty"><Spinner /></div></>
  const all = data.fields
  const unconf = all.filter((f) => f.status !== 'CONFIRMED')
  const sec = SECTIONS.find((s) => s.key === tab)
  const fields = (bySection[tab] || [])
  const visible = onlyOpen ? fields.filter((f) => f.status !== 'CONFIRMED' || f.flags.length || f.low_confidence) : fields

  return (
    <>
      <VoyageHeader voyage={voyage} current="review" />
      <div className="card">
        <div className="row">
          <div><b>{all.length - unconf.length}/{all.length}</b> trường đã xác nhận
            {unconf.length ? <span className="badge b-amber" style={{ marginLeft: 8 }}>{unconf.length} chưa xác nhận</span> : <span className="badge b-green" style={{ marginLeft: 8 }}>Đã xác nhận toàn bộ</span>}</div>
          <div className="spacer" />
          <label className="row small"><input type="checkbox" style={{ width: 'auto' }} checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} /> Chỉ hiện trường chưa xác nhận / có cảnh báo</label>
          <button className="btn" onClick={runCheck} disabled={rerun}>{rerun ? <Spinner /> : '↻'} Chạy lại đối chiếu</button>
          <button className="btn" onClick={() => setShowLog(true)}>Lịch sử chỉnh sửa</button>
          <Link className="btn primary" to={`/voyages/${id}/export`}>Tiếp: Xuất Excel →</Link>
        </div>
        <div className="small muted" style={{ marginTop: 10 }}>Sửa trực tiếp trong ô (lưu khi rời ô). Giá trị gốc từ chứng từ luôn được giữ và hiển thị gạch ngang khi đã sửa.
          Ô <span className="badge b-amber">vàng</span> = độ tin cậy thấp, <span className="badge b-red">đỏ</span> = đang có sai lệch/trùng lặp trong đối chiếu.</div>
      </div>

      <div className="tabs">
        {SECTIONS.map((s) => {
          const n = (bySection[s.key] || []).length
          const open = (bySection[s.key] || []).filter((f) => f.status !== 'CONFIRMED').length
          return <button key={s.key} className={tab === s.key ? 'on' : ''} onClick={() => setTab(s.key)}>{s.label}<span className="cnt">{n}</span>{open ? <span className="badge b-amber" style={{ marginLeft: 4 }}>{open}</span> : null}</button>
        })}
      </div>

      <div className="card tight">
        <div className="card-head">
          <h2>{sec.label}</h2>
          <div className="row">
            {tab !== 'vessel' && <button className="btn sm" onClick={() => setAdding(true)}>+ Thêm dòng nhập tay</button>}
            <button className="btn sm" onClick={() => confirm(fields.filter((f) => f.status === 'CONFIRMED').map((f) => f.id), false)}>Bỏ xác nhận nhóm</button>
            <button className="btn sm primary" onClick={() => confirm(fields.filter((f) => f.status !== 'CONFIRMED').map((f) => f.id))}>Xác nhận cả nhóm</button>
          </div>
        </div>
        {fields.length === 0 ? <div className="empty">Không có dữ liệu cho nhóm này (Not Available in Source). {tab !== 'vessel' && 'Có thể thêm dòng nhập tay nếu chứng từ có nhưng hệ thống không đọc được.'}</div>
          : tab === 'vessel' ? <VesselTable fields={visible} save={save} confirm={confirm} /> : <RecordTable fields={visible} cols={sec.cols} always={sec.always} labels={data.labels} save={save} confirm={confirm} reload={() => { load(); reload() }} voyageId={id} />}
      </div>
      {adding && <AddRecord section={sec} labels={data.labels} voyageId={id} onClose={() => setAdding(false)} onDone={() => { setAdding(false); load(); reload() }} />}
      {showLog && <LogModal voyageId={id} onClose={() => setShowLog(false)} />}
    </>
  )
}

const CT_OPTIONS = ['', 'Container 20', 'Container 40', 'Container 45', 'Other']

function AddCtype({ rec, voyageId, reload }) {
  const toast = useToast()
  const add = async (value) => {
    if (!value) return
    try {
      await api(`/api/voyages/${voyageId}/fields`, { method: 'POST', body: { document_id: rec.docId, section: 'cargo', record_key: rec.recordKey, field_key: 'container_type', value } })
      toast('Đã chọn loại container – cần xác nhận dòng này'); reload()
    } catch (e) { toast(e.message, 'err') }
  }
  return <select className="cell" value="" onChange={(e) => add(e.target.value)} style={{ minWidth: 140, borderColor: '#f59e0b', background: 'var(--amber-bg)' }}
    title="Chứng từ không ghi loại container – chọn sau khi kiểm tra bản gốc">{CT_OPTIONS.map((o) => <option key={o} value={o}>{o || '— chưa có, chọn —'}</option>)}</select>
}

function EditCell({ f, save, wide }) {
  const [v, setV] = useState(f.value || '')
  useEffect(() => setV(f.value || ''), [f.value])
  const bad = f.flags.some((x) => BAD.includes(x))
  const style = { borderColor: bad ? 'var(--red)' : f.low_confidence && f.status !== 'CONFIRMED' ? '#f59e0b' : undefined,
    background: bad ? 'var(--red-bg)' : f.low_confidence && f.status !== 'CONFIRMED' ? 'var(--amber-bg)' : undefined, minWidth: wide ? 220 : 110 }
  if (f.field_key === 'container_type') {
    const opts = CT_OPTIONS.includes(f.value || '') ? CT_OPTIONS : [f.value, ...CT_OPTIONS]
    return (
      <div>
        <select className="cell" value={f.value || ''} style={{ ...style, minWidth: 140 }} onChange={(e) => save(f, e.target.value)}
          title={`Nguồn: ${f.doc_name || 'Nhập tay'}${f.page_no ? ` – trang ${f.page_no}` : ''} · ${f.method || ''}`}>
          {opts.map((o) => <option key={o} value={o}>{o || '— chọn —'}</option>)}
        </select>
        {f.original_value != null && f.original_value !== f.value && <div className="orig" style={{ textDecoration: 'none' }} title="Ký hiệu gốc trong chứng từ">gốc: {f.original_value}</div>}
        {f.method === 'manual' && <div className="small muted">nhân viên chọn</div>}
      </div>
    )
  }
  return (
    <div>
      <input className="cell" value={v} style={style} onChange={(e) => setV(e.target.value)} onBlur={() => save(f, v)} onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
        title={`Nguồn: ${f.doc_name || 'Nhập tay'}${f.page_no ? ` – trang ${f.page_no}` : ''} · ${f.method || ''}`} />
      {f.original_value != null && f.original_value !== f.value && <div className="orig" title="Giá trị gốc trong chứng từ">{f.original_value}</div>}
    </div>
  )
}

function VesselTable({ fields, save, confirm }) {
  const sorted = [...fields].sort((a, b) => a.field_key.localeCompare(b.field_key) || (a.document_id || 0) - (b.document_id || 0))
  let prev = null
  return (
    <div className="scroll"><table className="t">
      <thead><tr><th>Trường</th><th>Giá trị (sửa được)</th><th>Nguồn chứng từ · trang</th><th>Tin cậy</th><th>Cảnh báo</th><th>Trạng thái</th><th /></tr></thead>
      <tbody>{sorted.map((f) => {
        const first = prev !== f.field_key
        prev = f.field_key
        return (
          <tr key={f.id} style={first ? { borderTop: '2px solid var(--border)' } : {}}>
            <td>{first ? <b>{f.field_label}</b> : ''}</td>
            <td><EditCell f={f} save={save} wide /></td>
            <td className="small">{f.doc_name || 'Nhập tay'}{f.page_no ? ` · tr.${f.page_no}` : ''}<div className="muted">{f.doc_type}</div></td>
            <td><Conf value={f.confidence} method={f.method} /></td>
            <td>{f.flags.map((x) => <Badge key={x} map={CHECK_STATUS} value={x} />)}</td>
            <td><Badge map={FIELD_STATUS} value={f.status} /></td>
            <td className="right">{f.status === 'CONFIRMED' ? <button className="btn sm ghost" onClick={() => confirm([f.id], false)}>Bỏ</button> : <button className="btn sm" onClick={() => confirm([f.id])}>✓ Xác nhận</button>}</td>
          </tr>)
      })}</tbody>
    </table></div>
  )
}

function RecordTable({ fields, cols, always = [], labels, save, confirm, reload, voyageId }) {
  const recs = new Map()
  for (const f of fields) {
    const k = `${f.document_id || 'm'}|${f.record_key}`
    if (!recs.has(k)) recs.set(k, { key: k, doc: f.doc_name, docId: f.document_id, recordKey: f.record_key, manual: !f.document_id, page: f.page_no, idx: f.record_index, f: {} })
    recs.get(k).f[f.field_key] = f
  }
  const present = cols.filter((c) => always.includes(c) || fields.some((f) => f.field_key === c))
  const extra = [...new Set(fields.map((f) => f.field_key))].filter((c) => !cols.includes(c) && c !== 'seq')
  const shownCols = [...present, ...extra]
  const delManual = async (r) => {
    if (!window.confirm('Xóa dòng nhập tay này?')) return
    await api(`/api/fields/${Object.values(r.f)[0].id}`, { method: 'DELETE' }); reload()
  }
  const rows = [...recs.values()]
  return (
    <div className="scroll"><table className="t">
      <thead><tr><th>#</th><th>Nguồn</th>{shownCols.map((c) => <th key={c}>{labels[c] || c}</th>)}<th>Trạng thái</th><th /></tr></thead>
      <tbody>{rows.map((r, i) => {
        const fs = Object.values(r.f)
        const done = fs.every((f) => f.status === 'CONFIRMED')
        return (
          <tr key={r.key}>
            <td className="small muted">{i + 1}</td>
            <td className="small" style={{ minWidth: 140 }}>{r.manual ? <span className="badge b-blue">Nhập tay</span> : r.doc}{r.page ? <div className="muted">trang {r.page}</div> : null}</td>
            {shownCols.map((c) => <td key={c}>{r.f[c] ? <><EditCell f={r.f[c]} save={save} wide={['full_name', 'shipper', 'consignee', 'description', 'proper_shipping_name', 'article', 'effects', 'notify'].includes(c)} />{r.f[c].confidence != null && r.f[c].low_confidence ? <Conf value={r.f[c].confidence} method={r.f[c].method} /> : null}</> : c === 'container_type' && r.f.container_no ? <AddCtype rec={r} voyageId={voyageId} reload={reload} /> : <span className="faint small">—</span>}</td>)}
            <td>{done ? <span className="badge b-green">Đã xác nhận</span> : <span className="badge b-gray">Chưa</span>}{fs.some((f) => f.flags.some((x) => BAD.includes(x))) && <div><span className="badge b-red">Sai lệch</span></div>}</td>
            <td className="right" style={{ whiteSpace: 'nowrap' }}>{done ? <button className="btn sm ghost" onClick={() => confirm(fs.map((f) => f.id), false)}>Bỏ</button>
              : <button className="btn sm" onClick={() => confirm(fs.filter((f) => f.status !== 'CONFIRMED').map((f) => f.id))}>✓ Xác nhận dòng</button>}
              {r.manual && <> <button className="btn sm danger" onClick={() => delManual(r)}>Xóa</button></>}</td>
          </tr>)
      })}</tbody>
    </table></div>
  )
}

function AddRecord({ section, labels, voyageId, onClose, onDone }) {
  const [vals, setVals] = useState({})
  const toast = useToast()
  const submit = async () => {
    try { await api(`/api/voyages/${voyageId}/records`, { method: 'POST', body: { section: section.key, fields: vals } }); toast('Đã thêm dòng nhập tay'); onDone() } catch (e) { toast(e.message, 'err') }
  }
  return (
    <Modal title={`Thêm dòng nhập tay – ${section.label}`} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Hủy</button><button className="btn primary" onClick={submit}>Thêm</button></>}>
      <div className="alert amber">Chỉ nhập thông tin có trên chứng từ gốc mà hệ thống không đọc được. Dòng này được đánh dấu “Nhập tay” và ghi vào lịch sử.</div>
      <div className="grid g2">{section.cols.filter((c) => c !== 'seq').map((c) => (
        <div className="field" key={c}><label className="f">{labels[c] || c}</label><input value={vals[c] || ''} onChange={(e) => setVals({ ...vals, [c]: e.target.value })} /></div>))}</div>
    </Modal>
  )
}

const ACTIONS = { EDIT_FIELD: 'Sửa giá trị', CONFIRM_FIELD: 'Xác nhận', UNCONFIRM_FIELD: 'Bỏ xác nhận', RESOLVE_MISMATCH: 'Xử lý sai lệch', ACK_DIFFERENCE: 'Chấp nhận khác biệt',
  UPLOAD: 'Tải chứng từ', EXTRACT: 'Trích xuất', CROSSCHECK: 'Đối chiếu', EXPORT_EXCEL: 'Xuất Excel', SET_DOC_TYPE: 'Đổi loại chứng từ', DELETE_DOCUMENT: 'Xóa chứng từ',
  ADD_MANUAL_RECORD: 'Thêm dòng nhập tay', SET_EXPORT_OPTION: 'Tùy chọn xuất', CREATE_VOYAGE: 'Tạo chuyến', EDIT_VOYAGE: 'Sửa chuyến', REPLACE_DOCUMENT: 'Thay file' }

export function LogModal({ voyageId, onClose }) {
  const [log, setLog] = useState(null)
  useEffect(() => { api(`/api/voyages/${voyageId}/log`).then(setLog) }, [voyageId])
  return (
    <Modal wide title="Lịch sử xử lý & chỉnh sửa" onClose={onClose}>
      {!log ? <Spinner /> : <div className="scroll"><table className="t">
        <thead><tr><th>Thời gian</th><th>Người thực hiện</th><th>Thao tác</th><th>Trường</th><th>Trước</th><th>Sau</th><th>Ghi chú</th></tr></thead>
        <tbody>{log.map((l) => <tr key={l.id}><td className="small">{l.at}</td><td>{l.user}</td><td>{ACTIONS[l.action] || l.action}</td><td className="small">{l.field_key}</td>
          <td className="small wrap-any orig" style={{ textDecoration: l.old_value ? 'line-through' : 'none' }}>{l.old_value}</td><td className="small wrap-any">{l.new_value}</td><td className="small wrap-any">{l.reason}</td></tr>)}</tbody>
      </table></div>}
    </Modal>
  )
}
