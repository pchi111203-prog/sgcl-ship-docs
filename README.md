# SGCL – Ship Documentation Automation System

Ứng dụng web hỗ trợ bộ phận Đại lý tàu biển SGCL tiếp nhận bộ chứng từ tàu, nhận diện – trích xuất – đối chiếu – xác nhận dữ liệu và xuất file Excel đúng mẫu khai báo NSW. Hệ thống **không** gửi dữ liệu lên Cổng NSW.

## 1. Kiến trúc & công nghệ

| Thành phần | Công nghệ | Lý do chọn |
|---|---|---|
| Giao diện | React 18 + Vite, CSS riêng theo nhận diện SGCL (teal) | Nhẹ, build nhanh, không phụ thuộc framework UI nặng |
| Backend/API | Python 3 + FastAPI | Hệ sinh thái Python mạnh nhất cho PDF/OCR/Excel |
| CSDL | SQLite (`backend/data/sgcl.db`) | Đủ cho prototype; schema chuẩn hóa, chuyển PostgreSQL dễ dàng |
| PDF văn bản | PyMuPDF (text, bố cục dòng) + pdfplumber (bảng có kẻ ô) | pdfplumber giữ nguyên khoảng trắng/dấu trong ô bảng |
| OCR | Tesseract 5 (eng + vie) | Miễn phí, chạy cục bộ, không gửi chứng từ ra ngoài |
| DOCX / XLSX | python-docx / openpyxl (chỉ đọc) | |
| Xuất Excel | **Chỉnh sửa trực tiếp XML của file mẫu** (`app/xlsxpatch.py`, lxml) | openpyxl làm mất Data Validation x14 của mẫu NSW; cách này giữ nguyên 100% cấu trúc |

```
backend/app/
  main.py          REST API, xử lý nền (thread pool), phân quyền
  db.py            Schema SQLite: users, vessel_profiles, voyages, documents, document_pages,
                   extracted_fields, crosscheck_runs/results/acks, review_log, export_options, exports
  ingest.py        Đọc PDF/ảnh/TIFF/DOCX/XLSX/CSV, OCR
  extract.py       Phân loại chứng từ theo nội dung + trích xuất theo nhãn và bảng
  normalize.py     Chuẩn hóa ngày/số/đơn vị, kiểm tra IMO & container (ISO 6346), danh mục mã NSW
  crosscheck.py    Đối chiếu 4 nhóm + chứng từ sai chuyến + chất lượng trích xuất
  nsw_export.py    Bảng ánh xạ → mẫu NSW, điều kiện xuất, ghi file, kiểm tra sau xuất
  xlsxpatch.py     Bộ ghi XLSX bảo toàn cấu trúc
  samples.py       Sinh bộ chứng từ MẪU cho 3 tình huống kiểm thử
backend/templates/TemplateNSW.xlsx   Mẫu NSW sạch (20 sheet, tạo từ HQ_NHAP.xlsx bằng tools/make_clean_template.py)
backend/tools/make_clean_template.py   Làm sạch một file NSW đã điền thành mẫu trắng (dùng khi có mẫu mới)
backend/tests/test_scenarios.py      Kiểm thử tự động 3 tình huống + cách ly dữ liệu chuyến
frontend/src/                        Giao diện React
docs/NSW_TEMPLATE_ANALYSIS.md        Phân tích mẫu NSW + câu hỏi cần SGCL xác nhận
```

Mỗi bảng dữ liệu đều gắn `voyage_id`; chuyến mới luôn bắt đầu trống. Mỗi trường trích xuất lưu: giá trị gốc, giá trị hiện tại, chứng từ nguồn, trang, phương pháp, độ tin cậy, trạng thái xác nhận. Mọi chỉnh sửa/xác nhận/xuất file được ghi vào `review_log`.

## 2. Khởi chạy

Yêu cầu: Python ≥ 3.10, Node.js ≥ 18, Tesseract OCR (`apt install tesseract-ocr tesseract-ocr-vie` / Windows: cài bộ UB Mannheim và thêm vào PATH). LibreOffice (tùy chọn) để kiểm tra độc lập file xuất.

```bash
cd backend && pip install -r requirements.txt
```
```bash
cd frontend && npm install && npm run build
```
```bash
./start.sh
```
Mở <http://localhost:8000>. **Tài khoản khởi tạo** (lần chạy đầu tiên): mật khẩu lấy từ biến môi trường `SGCL_ADMIN_PASSWORD`, `SGCL_STAFF_PASSWORD`; nếu không đặt, hệ thống tự sinh mật khẩu ngẫu nhiên, in ra cửa sổ máy chủ và lưu ở `backend/data/initial_credentials.txt`. Đổi mật khẩu tại Cài đặt hệ thống rồi xóa file đó. Đăng nhập sai 5 lần bị khóa 15 phút; phiên đăng nhập hết hạn sau 12 giờ.

Phát triển giao diện: chạy backend (`cd backend && uvicorn app.main:app --reload`) và `cd frontend && npm run dev` (http://localhost:5173, đã proxy `/api`).

Kiểm thử tự động:
```bash
cd backend && SGCL_DATA_DIR=$(mktemp -d) python3 -m pytest -q tests
```

Biến môi trường: `SGCL_DATA_DIR` (thư mục dữ liệu), `SGCL_TEMPLATE` (đường dẫn mẫu NSW), `SGCL_OCR_LANG` (VD `eng` để OCR nhanh hơn), `SGCL_SKIP_LIBREOFFICE=1`.

## 2b. Triển khai online: Railway (xử lý) + Vercel (giao diện)

- **Railway** build từ `Dockerfile` (cài sẵn Tesseract tiếng Việt). Cần gắn **Volume** vào `/data` để giữ dữ liệu. Biến môi trường: `SGCL_ADMIN_PASSWORD`, `SGCL_STAFF_PASSWORD`, `SGCL_CORS_ORIGINS=https://<tên>.vercel.app`.
- **Vercel** chỉ build giao diện theo `vercel.json`. Biến môi trường: `VITE_API_BASE=https://<địa-chỉ-railway>` (build lại sau khi đặt).
- Địa chỉ Railway cũng tự mở được giao diện (không bắt buộc dùng Vercel).

## 3. Hướng dẫn sử dụng

1. **Đăng nhập.**
2. **Tạo chuyến tàu mới** (menu 3): nhập thông tin cơ bản hoặc chọn Hồ sơ tàu (chỉ lấy tên/IMO/call sign/quốc tịch). Mỗi chuyến có mã riêng `SGCL-YYMM-NNNN`.
3. **Xử lý chứng từ** (menu 4): kéo thả nhiều file. Hệ thống tự nhận diện loại chứng từ theo nội dung và trích xuất (trạng thái: Đã tải lên → Đang xử lý → Đã trích xuất / Lỗi xử lý). Nếu nhận diện sai, chọn lại loại → trích xuất lại. “Xem” để thấy dữ liệu trích xuất và nội dung đọc được từng trang; “Thay file”, “Xóa”, “Xử lý lại”. Nút **Điền hồ sơ chuyến từ chứng từ** đề xuất tên tàu/IMO/ETA… từ GD/NOA (chỉ khi các chứng từ thống nhất, nhân viên chọn áp dụng).
4. **Đối chiếu dữ liệu** (menu 5): bấm “Chạy đối chiếu”. Kết quả theo nhóm, mỗi dòng hiển thị trường, 2 giá trị, 2 chứng từ, số trang, nội dung cảnh báo và đề xuất. Với sai lệch: “Xử lý…” → chọn giá trị đúng sau khi kiểm tra bản gốc (giá trị gốc vẫn lưu) **hoặc** “Chấp nhận khác biệt” kèm lý do (khi 2 chứng từ thể hiện phạm vi khác nhau).
5. **Kiểm tra và xác nhận** (menu 6): xem dữ liệu theo tab (Tàu & chuyến, Hàng hóa, Thuyền viên, …). Sửa trực tiếp trong ô; ô vàng = tin cậy thấp, ô đỏ = sai lệch. Xác nhận từng trường / dòng / cả nhóm. “Thêm dòng nhập tay” khi bản scan không đọc được. “Chạy lại đối chiếu” sau khi sửa.
6. **Xuất file Excel NSW** (menu 7): xem điều kiện xuất (lỗi chặn, cảnh báo, ô trống), nhập Tùy chọn (chức năng chứng từ, nơi/ngày/người ký, loại hộ chiếu, cách tách họ tên), chọn mã NSW cho giá trị chưa ánh xạ, xem trước dữ liệu từng sheet → **Xuất file Excel NSW** → xem báo cáo kiểm tra → **Tải xuống**. Khi còn lỗi, chỉ có thể “Xuất ngoại lệ” bằng tài khoản Supervisor + lý do (được ghi lại).
7. **Lịch sử xử lý** (menu 8): mở lại chuyến cũ, xem chứng từ, file đã xuất, nhật ký thao tác.
8. **Cài đặt** (menu 9): trạng thái OCR, cấu trúc mẫu, bảng ánh xạ, tài khoản, hồ sơ tàu, tạo **dữ liệu mẫu** cho 3 tình huống kiểm thử (gắn nhãn “DỮ LIỆU MẪU”, mã `SAMPLE-…`).

## 3b. Chức năng bổ sung (bản cập nhật Universal Multi-vessel)

- 16 loại chứng từ nhận diện theo nội dung (thêm Ship Security, Health, Plant, Animal, Empty Container List; không nhận diện được → *Unknown Document*, không bị bỏ qua). Đọc thêm **.xls**.
- Mỗi giá trị lưu: văn bản gốc, giá trị chuẩn hóa, chứng từ, trang, độ tin cậy, **kiểu dữ liệu, đơn vị**, trạng thái xác nhận.
- **Thông tin tàu tổng hợp** (tab Tàu & chuyến): so sánh GD/NOA/Tonnage, hiện nguồn, mâu thuẫn không tự chọn.
- **Possible Wrong Voyage Document** + cảnh báo trộn nhiều tàu trong một bộ: dữ liệu chứng từ nghi ngờ **không** vào Excel cho tới khi nhân viên *Xác nhận đúng hồ sơ* / *Chuyển sang chuyến khác* / *Xóa*. Chứng từ không ghi tên tàu/IMO/số chuyến → *Needs Manual Review*.
- Đối chiếu nhóm **5. Container** (Manifest, B/L, Empty Container List, DG).
- **Loại bỏ / khôi phục bản ghi** trích xuất (VD dòng tổng cộng đọc nhầm), giá trị gốc vẫn giữ.
- Cảnh báo **trùng hồ sơ chuyến** (cùng IMO/tên tàu + số chuyến + cảng đến + ETA); hồ sơ mới là *hồ sơ nháp*.
- Tiến trình: Uploaded → Classified → Extracted → Cross-checked → Reviewed → Ready to Export → Exported.
- Nút **Trích xuất tất cả** (chỉ chứng từ chưa xử lý / lỗi); danh sách **Unmapped Fields** ở trang Xuất Excel.
- Bản khai an ninh → sheet *Declaration For Ship Security* (ISSC, cấp độ an ninh, 10 cảng ghé); Empty Container List → sheet *Empty Container*.
- Dữ liệu mẫu: 4 bộ (đầy đủ; sai lệch + nhiều B/L + container + an ninh; scan/thiếu/không nhận diện; 5 chứng từ với 35 thuyền viên & 50 dòng hàng).

## 4. Giới hạn hiện tại (cần biết)

- Trích xuất là **dựa trên quy tắc** (nhãn trường, tiêu đề cột). Chứng từ có bố cục lạ hoặc manifest dạng khối phức tạp có thể bị bỏ sót trường → hệ thống báo “Not Available in Source”/“Missing Information”, không tự bịa. Chưa tích hợp AI (LLM) vì cần API key và chính sách gửi chứng từ ra ngoài – đây là hướng nâng cấp đề xuất cho chứng từ bố cục tự do.
- OCR bảng dày đặc trên bản scan kém chất lượng thường **không đọc được** (đã thử trong tình huống 3): hệ thống báo lỗi “không trích xuất được dòng thuyền viên” và cho nhập tay. OCR chỉ đáng tin với bản scan rõ ≥ 300 dpi.
- Ngày dạng số được hiểu theo thứ tự **ngày/tháng/năm**.
- Đăng nhập là cơ chế nội bộ đơn giản (prototype) – khi triển khai thật cần HTTPS và tích hợp tài khoản công ty.
- Các điểm ánh xạ chưa xác định được xem `docs/NSW_TEMPLATE_ANALYSIS.md` mục 4.
