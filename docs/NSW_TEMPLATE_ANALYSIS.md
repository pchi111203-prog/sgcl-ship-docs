# Phân tích file mẫu NSW (`TemplateNSW.xlsx`)

## 1. Cấu trúc tổng quát

| # | Sheet | Trạng thái | Vai trò | Hệ thống xử lý |
|---|-------|-----------|---------|----------------|
| 1 | Declaration list | hiện | **Danh mục mã** (quốc gia, chức danh, đơn vị tính, loại kiện, loại container, loại hộ chiếu, mã hàng…) – nguồn của các dropdown | **Không bao giờ sửa**; đọc khi khởi động để lấy danh mục mã |
| 2 | Notice ship to port | hiện | Thông báo tàu đến/rời (B3–B32), chất thải (A36:C41), nhóm hàng (A44:G46) | Điền B3–B31 (nguồn NOA → GD); xóa mẫu ở 2 bảng |
| 3 | ConfirmationOfArrival | hiện | Xác báo tàu đến (thời gian thực tế, người trên tàu) | Chỉ tùy chọn chung; xóa mẫu |
| 4 | Goods Declaration | hiện | Bản khai hàng hóa – 1 dòng / B/L-container từ dòng 10 (A:W) | Điền từ Cargo Manifest (hoặc B/L) – số dòng thay đổi |
| 5 | List of House bill of lading | hiện | Khối 8 dòng / House B/L | **Chỉ xóa mẫu** (xem câu hỏi Q5) |
| 6 | General Declaration | hiện | Bản khai chung (B3–B34), chất thải (A38:C43), nhóm hàng (A46:G51) | Điền B3–B32 (nguồn GD → NOA) |
| 7 | Crew list | hiện | Danh sách thuyền viên từ dòng 11 (A:K) | Điền – số dòng thay đổi |
| 8 | Crew's Effects Declaration | hiện | Hành lý thuyền viên từ dòng 11 (A:D) | Điền – tối đa đến dòng 44 (dòng 45–54 cột C:E có nội dung của mẫu) |
| 9 | Ship's store declaration | hiện | Dự trữ tàu từ dòng 13 (A:E) | Điền |
| 10 | Passenger list | hiện | Hành khách từ dòng 11 (A:M) | Điền |
| 11 | Cargo manifest | **ẩn** | Bản lược khai dạng tổng hợp (hình thức chuyển tải, TEU…) | Giữ ẩn, chỉ xóa mẫu |
| 12 | Dangerous goods manifest | hiện | Hàng nguy hiểm từ dòng 14 (A:P) | Điền |
| 13–21 | Ship Security, Plant, Animal, Health, Empty Container, Arms & Explosive, Stowaway, Add User, InlandAttachmentList | hiện | Các bản khai khác | Chỉ xóa mẫu (bộ chứng từ hiện tại không có nguồn) |

Quy ước chung các sheet bản khai: **A = nhãn (Việt/Anh), B = giá trị**; B3 Số hồ sơ, B4 Năm đăng ký, B5 Chức năng chứng từ (`CN01` Thêm mới / `CN02` Sửa / `CN03` Xóa), C5 = công thức VLOOKUP tên chức năng.

## 2. Các yếu tố kỹ thuật đặc biệt (và cách xử lý)

| Yếu tố | Phát hiện | Cách xử lý |
|--------|-----------|-----------|
| Data Validation x14 (dropdown trỏ sang sheet khác) | 7 validation dạng extension (VD: Crew list C11 → `'Declaration list'!$R$3:$R$76`; Passenger G11 loại hộ chiếu) + 113 validation thường | **openpyxl xóa mất x14 khi lưu** → hệ thống ghi trực tiếp XML (`xlsxpatch.py`), giữ nguyên mọi thành phần; khi danh sách dài thêm, phạm vi dropdown được mở rộng theo |
| Liên kết ngoài | 9 external links; công thức dạng `'[4]Declaration list'!…`, `'[4]Notice ship to port'!$B$15` | Giữ nguyên byte-by-byte. Các ô này sẽ báo lỗi tham chiếu khi mở ở máy không có file gốc (vốn có sẵn trong mẫu) |
| Ô công thức ở vị trí nhập liệu | GD B33 (Ngày ký), B34 (Người ký); NOA B32; ConfirmationOfArrival B10 | **Không ghi đè công thức** (xem Q3) |
| Công thức theo dòng | `D44 =VLOOKUP(C44,…)` (nhóm hàng), `E8` Empty Container, `B8` Arms, `Y13…` Stowaway | Khi sinh dòng mới, công thức được sao chép và dịch tham chiếu cùng dòng |
| Giá trị dạng text | Ngày, số lượng trong mẫu đều lưu dạng chuỗi (`'25/05/2017 08:00'`, `'999'`) | Xuất dạng chuỗi: ngày `dd/mm/yyyy` hoặc `dd/mm/yyyy HH:MM`, số không có dấu phân cách nghìn |
| Comments, VML, printer settings, styles | 20 file comments, 20 VML | Giữ nguyên |
| calcChain | có | Loại bỏ (Excel tự dựng lại) + bật `fullCalcOnLoad` |
| Dòng trống đã định dạng sẵn | VD Crew list dòng 12–20 | Thay bằng dòng sao chép từ dòng mẫu |
| Named range `PortList` | trỏ `'Declaration list'!$G$3:$G$12988` nhưng cột G thực tế là **danh mục hàng hóa (88 dòng)** – workbook **không có danh mục mã cảng UN/LOCODE** | Mã cảng lấy từ chứng từ (VD `(VNCLI)`), nếu không có → ghi nguyên văn + cảnh báo (xem Q4) |

## 3. Kiểm tra tự động sau khi xuất

1. Mở được bằng openpyxl; 2. mở được bằng LibreOffice (độc lập); 3. đủ 21 sheet, đúng tên, thứ tự, trạng thái ẩn; 4. mọi ô đã ghi đọc lại đúng giá trị; 5. công thức của mẫu còn nguyên; 6. không còn dữ liệu mẫu/chuyến cũ trong vùng nhập liệu; 7. số Data Validation (thường + x14) bằng mẫu; 8. styles/comments/external links giống hệt mẫu; 9. sheet `Declaration list` không đổi.

## 4. Những điểm CẦN SGCL XÁC NHẬN (hệ thống đang để mặc định an toàn)

| # | Câu hỏi | Mặc định hiện tại |
|---|---------|------------------|
| Q1 | Crew/Passenger list: dòng mẫu ghi **cùng một họ tên đầy đủ ở cả cột Họ và cột Tên**. NSW yêu cầu tách hay ghi như vậy? | Theo dòng mẫu (họ tên đầy đủ ở cả 2 cột); có tùy chọn tách “Họ = từ đầu…/Tên = từ cuối” |
| Q2 | B3 Số hồ sơ / B4 Năm đăng ký: do NSW cấp hay đại lý tự điền? | Để trống (có ô nhập ở Tùy chọn xuất file) |
| Q3 | GD B33/B34, NOA B32: đang là công thức tham chiếu file ngoài. Có được thay bằng giá trị nhập không? | Giữ công thức, không ghi đè |
| Q4 | Mã cảng (UN/LOCODE) cho Goods Declaration P/R, DG B6/B7: lấy từ danh mục nào? | Lấy mã 5 ký tự có trong chứng từ; nếu không có → ghi nguyên văn + cảnh báo, nhân viên nhập mã |
| Q5 | “List of House bill of lading”: làm sao phân biệt House B/L và Master B/L trong bộ chứng từ của SGCL? | Chưa điền, chỉ xóa mẫu |
| Q6 | B14–B19 GD/NOA (“số bản” các bản khai kèm theo): ghi số lượng bản hay 1/0? | Để trống, nhập tay nếu cần |
| Q7 | Goods Declaration: 1 dòng / container hay 1 dòng / B/L khi 1 B/L có nhiều container? Cột V “Loại cont” bắt buộc nhưng chứng từ thường không ghi 20/40/45 | 1 dòng / dòng manifest. Cột V: tự nhận diện từ chứng từ (20GP/40HC/45HC, mã ISO 22G1/45G1/L5G1, cột Size/Type); thiếu thì nhân viên chọn ở tab Hàng hóa |
| Q8 | Sheet ẩn “Cargo manifest” có còn dùng không? | Giữ ẩn, chỉ xóa mẫu |
| Q9 | Bảng chất thải (A38:C43) và nhóm hàng C1_XEP/C2_DO… (A46:G51) cần phân loại theo danh mục NSW – quy tắc phân loại của SGCL? | Chưa điền (không tự suy đoán) |
| Q10 | B5 Chức năng chứng từ ở các sheet không có dữ liệu: giữ `CN01` hay để trống? | Ghi giá trị chọn ở Tùy chọn (mặc định `CN01`) cho mọi sheet |
