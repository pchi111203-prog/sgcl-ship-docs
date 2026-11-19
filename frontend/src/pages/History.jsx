import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fileUrl } from '../api'
import { Badge, DOC_STATUS, Spinner, VOYAGE_STATUS } from '../components'
import { LogModal } from './Review'

export default function History() {
  const [list, setList] = useState(null)
  const [open, setOpen] = useState(null)
  const [log, setLog] = useState(null)
  useEffect(() => { api('/api/history').then(setList) }, [])
  if (!list) return <div className="empty"><Spinner /></div>
  return (
    <>
      <div className="page-head"><div><h1>Lịch sử xử lý</h1><p>Toàn bộ chuyến tàu, chứng từ, trạng thái và file Excel đã xuất. Mở lại chuyến cũ để xem – dữ liệu của mỗi chuyến tách biệt.</p></div></div>
      <div className="card tight">
        <table className="t">
          <thead><tr><th>Mã chuyến</th><th>Tên tàu</th><th>Ngày tạo</th><th>Chứng từ</th><th>Trích xuất</th><th>Đối chiếu</th><th>Xác nhận</th><th>File Excel</th><th>Trạng thái</th><th /></tr></thead>
          <tbody>
            {list.map((v) => {
              const p = v.progress
              return [
                <tr key={v.id} className={open === v.id ? 'sel' : ''}>
                  <td className="mono">{v.voyage_code}</td>
                  <td><b>{v.vessel_name || '—'}</b> {v.voyage_no} {v.is_sample ? <span className="badge b-sample">MẪU</span> : null}</td>
                  <td className="small">{v.created_at}</td>
                  <td>{p.documents}</td>
                  <td>{p.documents ? `${p.extracted}/${p.documents}` : '—'}{p.errors ? <span className="badge b-red" style={{ marginLeft: 4 }}>{p.errors} lỗi</span> : null}</td>
                  <td className="small">{p.last_check ? <>{p.last_check}<br />{p.blocking ? <span className="badge b-red">{p.blocking} chặn</span> : <span className="badge b-green">Không lỗi chặn</span>}</> : '—'}</td>
                  <td>{p.fields ? `${p.confirmed}/${p.fields}` : '—'}</td>
                  <td className="small">{v.exports.length ? <>{v.exports.length} file<br />{v.exports[0].created_at}</> : '—'}</td>
                  <td><Badge map={VOYAGE_STATUS} value={p.status} /></td>
                  <td className="right" style={{ whiteSpace: 'nowrap' }}>
                    <button className="btn sm" onClick={() => setOpen(open === v.id ? null : v.id)}>{open === v.id ? 'Thu gọn' : 'Chi tiết'}</button>{' '}
                    <button className="btn sm" onClick={() => setLog(v.id)}>Nhật ký</button>{' '}
                    <Link className="btn sm primary" to={`/voyages/${v.id}/documents`}>Mở</Link>
                  </td>
                </tr>,
                open === v.id && <tr key={v.id + 'd'}><td colSpan={10} style={{ background: '#fbfcfd' }}>
                  <div className="grid g2">
                    <div><h3>Chứng từ đã tải lên</h3>{v.documents.length ? v.documents.map((d) => <div key={d.id} className="small row" style={{ marginBottom: 3 }}>
                      <Badge map={DOC_STATUS} value={d.status} /> {d.original_name} <span className="muted">({d.doc_type || '—'}) · {d.uploaded_at}</span></div>) : <span className="muted small">Không có</span>}</div>
                    <div><h3>File Excel đã xuất</h3>{v.exports.length ? v.exports.map((e) => <div key={e.id} className="small row" style={{ marginBottom: 3 }}>
                      <a href={fileUrl(`/api/exports/${e.id}/download`)}>⬇ {e.file_name}</a><span className="muted">{e.created_at} · {e.created_by}</span>{e.override_used ? <span className="badge b-red">Ngoại lệ</span> : null}</div>) : <span className="muted small">Chưa xuất</span>}</div>
                  </div>
                </td></tr>,
              ]
            })}
            {!list.length && <tr><td colSpan={10} className="empty">Chưa có lịch sử.</td></tr>}
          </tbody>
        </table>
      </div>
      {log && <LogModal voyageId={log} onClose={() => setLog(null)} />}
    </>
  )
}
