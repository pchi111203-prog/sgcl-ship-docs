import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Badge, Progress, Spinner, VOYAGE_STATUS } from '../components'

export default function Dashboard() {
  const [d, setD] = useState(null)
  const nav = useNavigate()
  useEffect(() => { api('/api/dashboard').then(setD) }, [])
  if (!d) return <div className="empty"><Spinner /></div>
  const s = d.stats
  const tiles = [
    ['Tổng số chuyến tàu', s.voyages], ['Chuyến đang xử lý', s.in_progress], ['Chứng từ đã tải lên', s.documents],
    ['Trích xuất thành công', s.extracted, 'green'], ['Lỗi cần kiểm tra', s.issues + s.doc_errors, s.issues + s.doc_errors ? 'red' : ''], ['File Excel đã xuất', s.exports],
  ]
  return (
    <>
      <div className="page-head">
        <div><h1>Dashboard</h1><p>Tổng quan xử lý chứng từ khai báo tàu nhập cảnh</p></div>
        <Link to="/voyages/new" className="btn primary">+ Tạo chuyến tàu mới</Link>
      </div>
      <div className="grid g6" style={{ marginBottom: 18 }}>
        {tiles.map(([l, v, c]) => <div key={l} className={`stat ${c || ''}`}><div className="lbl">{l}</div><div className="val">{v}</div></div>)}
      </div>
      <div className="card tight">
        <div className="card-head"><h2>Chuyến tàu gần đây</h2><Link to="/voyages">Xem tất cả →</Link></div>
        {d.recent.length === 0 ? <div className="empty">Chưa có chuyến tàu nào. Bấm “Tạo chuyến tàu mới” để bắt đầu, hoặc tạo bộ dữ liệu mẫu tại <Link to="/settings">Cài đặt hệ thống</Link>.</div> : (
          <table className="t">
            <thead><tr><th>Mã chuyến</th><th>Tên tàu</th><th>IMO</th><th>Voyage No.</th><th>Cảng đến</th><th>ETA</th><th>Ngày tạo</th><th>Trạng thái</th><th style={{ width: 160 }}>Tiến độ</th></tr></thead>
            <tbody>
              {d.recent.map((v) => (
                <tr key={v.id} style={{ cursor: 'pointer' }} onClick={() => nav(`/voyages/${v.id}/documents`)}>
                  <td className="mono">{v.voyage_code}</td>
                  <td><b>{v.vessel_name || '—'}</b> {v.is_sample ? <span className="badge b-sample">MẪU</span> : null}
                    {v.archived_at ? <span className="badge b-gray" style={{ marginLeft: 4 }} title={`Lưu trữ lúc ${v.archived_at}`}>Lưu trữ</span> : null}</td>
                  <td>{v.imo || '—'}</td><td>{v.voyage_no || '—'}</td><td>{v.port_of_arrival || '—'}</td><td>{v.eta || '—'}</td>
                  <td className="small">{v.created_at}</td>
                  <td><Badge map={VOYAGE_STATUS} value={v.progress.status} />{v.progress.blocking ? <span className="badge b-red" style={{ marginLeft: 4 }}>{v.progress.blocking} lỗi</span> : null}</td>
                  <td><Progress value={v.progress.progress} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="card">
        <h2>Quy trình xử lý</h2>
        <ol className="muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9 }}>
          <li>Tạo chuyến tàu mới (mỗi chuyến có Mã chuyến riêng, dữ liệu bắt đầu trống).</li>
          <li>Tải lên bộ chứng từ → hệ thống tự nhận diện loại chứng từ và trích xuất dữ liệu (đọc văn bản PDF/DOCX/XLSX, OCR cho bản scan/ảnh).</li>
          <li>Chạy đối chiếu giữa các chứng từ → xem các sai lệch, thiếu thông tin, trùng lặp, độ tin cậy thấp.</li>
          <li>Kiểm tra, chỉnh sửa và xác nhận dữ liệu (giá trị gốc luôn được lưu lại).</li>
          <li>Xuất file Excel theo đúng mẫu NSW → hệ thống tự kiểm tra file sau khi xuất → tải xuống.</li>
        </ol>
      </div>
    </>
  )
}
