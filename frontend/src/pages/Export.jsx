import { useCallback, useEffect, useState } from 'react'
import { api, fileUrl } from '../api'
import { Modal, Spinner, useToast, useVoyage, VoyageHeader } from '../components'

// Same normalisation as backend normalize.norm_text (used as key for code-mapping overrides)
const normText = (s) => (s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd').replace(/Đ/g, 'D').toUpperCase()
  .replace(/[\s.,;:\-_/\\'"()]+/g, ' ').trim()
const KIND_LABEL = { rank: 'Chức danh', state: 'Quốc tịch', gender: 'Giới tính', package: 'Loại kiện', unit: 'Đơn vị tính', locode: 'Mã cảng (UN/LOCODE)' }

export default function Export({ user }) {
  const { id, voyage, reload } = useVoyage()
  const [rd, setRd] = useState(null)
  const [opt, setOpt] = useState(null)
  const [form, setForm] = useState({})
  const [exports, setExports] = useState([])
  const [busy, setBusy] = useState(false)
  const [override, setOverride] = useState(false)
  const [tab, setTab] = useState('cells')
  const toast = useToast()

  const load = useCallback(() => {
    api(`/api/voyages/${id}/export/readiness`).then(setRd)
    api(`/api/voyages/${id}/export/options`).then((o) => { setOpt(o); setForm(o.options) })
    api(`/api/voyages/${id}/exports`).then(setExports)
  }, [id])
  useEffect(() => { load() }, [load])

  const saveOpts = async (extra) => {
    try { await api(`/api/voyages/${id}/export/options`, { method: 'PUT', body: { ...form, ...(extra || {}) } }); toast('Đã lưu tùy chọn'); load() } catch (e) { toast(e.message, 'err') }
  }
  const doExport = async (ov) => {
    setBusy(true)
    try {
      const r = await api(`/api/voyages/${id}/export`, { method: 'POST', body: ov || {} })
      const failed = r.report.checks.filter((c) => !c.ok)
      toast(failed.length ? `Đã xuất file nhưng có ${failed.length} mục kiểm tra không đạt – xem báo cáo` : 'Đã xuất file Excel và kiểm tra đạt yêu cầu', failed.length ? 'warn' : 'ok')
      setOverride(false); load(); reload()
    } catch (e) { toast(e.message, 'err') } finally { setBusy(false) }
  }
  if (!rd || !opt) return <><VoyageHeader voyage={voyage} current="export" /><div className="empty"><Spinner /></div></>
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const unmapped = rd.plan.unmapped_codes.map((x) => { const [kind, raw] = x.split('|'); return { kind, raw } })

  return (
    <>
      <VoyageHeader voyage={voyage} current="export" />
      <div className="grid g2">
        <div className="card">
          <h2>Kiểm tra điều kiện xuất file</h2>
          {rd.ready ? <div className="alert green">Đủ điều kiện xuất file: không còn lỗi nghiêm trọng, toàn bộ dữ liệu xuất ra đã được xác nhận.</div>
            : <div className="alert red"><b>Chưa đủ điều kiện xuất file:</b><ul>{rd.blockers.slice(0, 12).map((b, i) => <li key={i}>{b}</li>)}{rd.blockers.length > 12 && <li>… và {rd.blockers.length - 12} mục khác</li>}</ul></div>}
          {rd.warnings.length > 0 && <div className="alert amber"><b>Lưu ý ({rd.warnings.length}):</b><ul>{rd.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></div>}
          <details><summary className="small" style={{ cursor: 'pointer' }}>{rd.empty.length} ô trong mẫu NSW chưa có dữ liệu (để trống, không tự điền)</summary>
            <ul className="small muted">{rd.empty.map((x, i) => <li key={i}>{x}</li>)}</ul></details>
          <hr />
          <div className="row">
            <button className="btn primary" disabled={!rd.ready || busy} onClick={() => doExport()}>{busy ? <><Spinner /> Đang tạo & kiểm tra file…</> : 'Xuất file Excel NSW'}</button>
            {!rd.ready && <button className="btn" onClick={() => setOverride(true)}>Xuất ngoại lệ (cần Supervisor)…</button>}
          </div>
          <p className="small muted">Hệ thống chỉ tạo file Excel để nhân viên kiểm tra và sử dụng. Không tự động gửi dữ liệu lên Cổng thông tin một cửa quốc gia.</p>
        </div>

        <div className="card">
          <h2>Tùy chọn xuất file</h2>
          <div className="grid g3">
            <div className="field"><label className="f">Chức năng chứng từ (B5)</label><select value={form.doc_function || ''} onChange={set('doc_function')}>
              {Object.entries(opt.doc_functions).map(([k, v]) => <option key={k} value={k}>{k} – {v}</option>)}</select></div>
            <div className="field"><label className="f">Số hồ sơ (B3)</label><input value={form.doc_no || ''} onChange={set('doc_no')} placeholder="để trống nếu NSW cấp" /></div>
            <div className="field"><label className="f">Năm đăng ký (B4)</label><input value={form.doc_year || ''} onChange={set('doc_year')} /></div>
          </div>
          <div className="grid g3">
            <div className="field"><label className="f">Nơi ký</label><input value={form.sign_place || ''} onChange={set('sign_place')} /></div>
            <div className="field"><label className="f">Ngày ký</label><input value={form.sign_date || ''} onChange={set('sign_date')} placeholder="dd/mm/yyyy" /></div>
            <div className="field"><label className="f">Người ký</label><select value={form.signer || ''} onChange={set('signer')}><option value="">—</option>{opt.signers.map((s) => <option key={s}>{s}</option>)}</select></div>
          </div>
          <div className="grid g2">
            <div className="field"><label className="f">Loại hộ chiếu – Crew list (cột G)</label><select value={form.crew_passport_type || ''} onChange={set('crew_passport_type')}>
              <option value="">— để trống —</option>{Object.entries(opt.passport_types).map(([k, v]) => <option key={k} value={k}>{k} – {v}</option>)}</select>
              <div className="hint">Chứng từ thường không ghi loại giấy tờ → nhân viên chọn.</div></div>
            <div className="field"><label className="f">Tách Họ / Tên khi chứng từ chỉ có họ tên đầy đủ</label><select value={form.name_split || ''} onChange={set('name_split')}>
              {Object.entries(opt.name_splits).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
          </div>
          <button className="btn primary" onClick={() => saveOpts()}>Lưu tùy chọn</button>
        </div>
      </div>

      {unmapped.length > 0 && <div className="card">
        <h2>Ánh xạ mã NSW ({unmapped.length} giá trị chưa có mã)</h2>
        <p className="small muted">Các giá trị dưới đây không khớp danh mục trong sheet “Declaration list” của mẫu. Chọn mã đúng (áp dụng cho chuyến này, được ghi vào lịch sử).</p>
        <table className="t"><thead><tr><th>Loại</th><th>Giá trị trong chứng từ</th><th>Mã NSW</th></tr></thead><tbody>
          {unmapped.map(({ kind, raw }) => {
            const key = `code:${kind}:${normText(raw)}`
            const codes = opt.codes[kind]
            return <tr key={key}><td>{KIND_LABEL[kind] || kind}</td><td className="mono">{raw}</td><td>
              {codes ? <select value={form[key] || ''} onChange={(e) => saveOpts({ [key]: e.target.value })} style={{ maxWidth: 380 }}>
                <option value="">— chọn mã —</option>{(Array.isArray(codes) ? codes.map((c) => [c, c]) : Object.entries(codes)).map(([c, n]) => <option key={c} value={c}>{c} – {n}</option>)}</select>
                : <input defaultValue={form[key] || ''} placeholder="VD: VNCLI" onBlur={(e) => e.target.value !== (form[key] || '') && saveOpts({ [key]: e.target.value.toUpperCase() })} style={{ maxWidth: 200 }} />}
            </td></tr>
          })}</tbody></table>
      </div>}

      <div className="card tight">
        <div className="card-head"><h2>Xem trước dữ liệu sẽ điền vào file mẫu</h2></div>
        <div style={{ padding: '0 18px' }}>
          <div className="tabs" style={{ marginTop: 10 }}>
            <button className={tab === 'cells' ? 'on' : ''} onClick={() => setTab('cells')}>Ô thông tin chung<span className="cnt">{rd.plan.cells.length}</span></button>
            {Object.entries(rd.plan.tables).map(([s, t]) => <button key={s} className={tab === s ? 'on' : ''} onClick={() => setTab(s)}>{s}<span className="cnt">{t.rows.length}</span></button>)}
            <button className={tab === 'manual' ? 'on' : ''} onClick={() => setTab('manual')}>Giá trị nhập tay</button>
          </div>
        </div>
        {tab === 'cells' && <div className="scroll"><table className="t"><thead><tr><th>Sheet</th><th>Ô</th><th>Nội dung</th><th>Giá trị</th><th>Nguồn</th></tr></thead><tbody>
          {rd.plan.cells.map((c) => <tr key={c.sheet + c.cell}><td>{c.sheet}</td><td className="mono">{c.cell}</td><td>{c.label}</td><td className="mono">{c.value}</td>
            <td className="small">{c.sources.map((s, i) => <div key={i}>{s.doc}{s.page ? ` · tr.${s.page}` : ''} {s.status && s.status !== 'CONFIRMED' && <span className="badge b-amber">{s.status === 'DERIVED' ? 'Tính từ dữ liệu' : 'Chưa xác nhận'}</span>}</div>)}</td></tr>)}
        </tbody></table></div>}
        {rd.plan.tables[tab] && <TablePreview t={rd.plan.tables[tab]} />}
        {tab === 'manual' && <ManualCells opt={opt} form={form} save={saveOpts} />}
      </div>

      <div className="card tight">
        <div className="card-head"><h2>File đã xuất ({exports.length})</h2></div>
        {!exports.length ? <div className="empty">Chưa xuất file nào.</div> : exports.map((e) => (
          <div key={e.id} style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)' }}>
            <div className="row"><b>{e.file_name}</b>{e.override_used ? <span className="badge b-red">Xuất ngoại lệ – {e.override_by}: {e.override_reason}</span> : null}
              <span className="small muted">{e.created_at} · {e.created_by}</span><div className="spacer" />
              <a className="btn primary sm" href={fileUrl(`/api/exports/${e.id}/download`)}>⬇ Tải xuống</a></div>
            <div className="grid g2" style={{ marginTop: 10 }}>
              <div>{e.report.checks?.map((c, i) => <div key={i} className="small">{c.ok ? '✅' : '❌'} {c.check} {c.detail && <span className="muted">({c.detail})</span>}</div>)}</div>
              <div className="small muted">Đã ghi {e.report.cells_written} ô. Số dòng: {Object.entries(e.report.rows || {}).map(([s, n]) => `${s}: ${n}`).join(' · ') || '—'}
                {e.report.empty?.length ? <div>{e.report.empty.length} ô mẫu chưa có dữ liệu (để trống).</div> : null}</div>
            </div>
          </div>))}
      </div>
      {override && <OverrideModal blockers={rd.blockers} onClose={() => setOverride(false)} onSubmit={doExport} busy={busy} />}
    </>
  )
}

function TablePreview({ t }) {
  const cols = [...new Set(t.rows.flatMap((r) => Object.keys(r)))].sort((a, b) => a.length - b.length || a.localeCompare(b))
  return <div className="scroll"><table className="t"><thead><tr><th>#</th>{cols.map((c) => <th key={c}>Cột {c}</th>)}<th>Nguồn</th></tr></thead><tbody>
    {t.rows.map((r, i) => <tr key={i}><td className="muted small">{i + 1}</td>{cols.map((c) => <td key={c} className="small">{r[c] ?? ''}</td>)}
      <td className="small muted">{[...new Set((t.sources[i] || []).map((s) => `${s.doc}${s.page ? ' tr.' + s.page : ''}`))].join(', ')}</td></tr>)}
  </tbody></table></div>
}

function ManualCells({ opt, form, save }) {
  return <div className="scroll"><table className="t"><thead><tr><th>Sheet</th><th>Ô</th><th>Nội dung</th><th>Nguồn mặc định</th><th>Giá trị nhập tay (ghi đè)</th></tr></thead><tbody>
    {opt.manual_cells.map((m) => {
      const key = `cell:${m.sheet}!${m.cell}`
      return <tr key={key}><td>{m.sheet}</td><td className="mono">{m.cell}</td><td>{m.label}</td>
        <td className="small muted">{m.spec.startsWith('src') ? 'Từ chứng từ' : m.spec.startsWith('derived') ? 'Tính từ dữ liệu' : 'Không có trong chứng từ'}</td>
        <td><input className="cell" defaultValue={form[key] || ''} onBlur={(e) => e.target.value !== (form[key] || '') && save({ [key]: e.target.value })} /></td></tr>
    })}</tbody></table>
    <p className="small muted" style={{ padding: '0 18px' }}>Chỉ nhập khi có căn cứ (chứng từ gốc, chỉ thị của cảng vụ…). Giá trị nhập tay được ghi vào lịch sử.</p></div>
}

function OverrideModal({ blockers, onClose, onSubmit, busy }) {
  const [f, setF] = useState({ override_username: '', override_password: '', override_reason: '' })
  return (
    <Modal title="Xuất file ngoại lệ" onClose={onClose} footer={<><button className="btn" onClick={onClose}>Hủy</button>
      <button className="btn danger" disabled={busy || !f.override_reason.trim()} onClick={() => onSubmit(f)}>Xác nhận xuất ngoại lệ</button></>}>
      <div className="alert red">File sẽ được xuất dù còn {blockers.length} vấn đề chưa xử lý. Việc này được ghi lại cùng tên Supervisor và lý do.</div>
      <div className="field"><label className="f req">Tài khoản Supervisor</label><input value={f.override_username} onChange={(e) => setF({ ...f, override_username: e.target.value })} /></div>
      <div className="field"><label className="f req">Mật khẩu</label><input type="password" value={f.override_password} onChange={(e) => setF({ ...f, override_password: e.target.value })} /></div>
      <div className="field"><label className="f req">Lý do</label><textarea rows={3} value={f.override_reason} onChange={(e) => setF({ ...f, override_reason: e.target.value })} /></div>
    </Modal>
  )
}
