# Phân tích file mẫu NSW

> **Cập nhật 20/11/2026:** mẫu đang dùng được tạo từ file **HQ_NHAP.xlsx** (bản khai NSW thực tế mới nhất của SGCL) bằng
> `backend/tools/make_clean_template.py`: toàn bộ dữ liệu chuyến tàu trong file (thuyền viên, vận đơn, hàng hóa, cảng ghé…) đã bị xóa,
> chuỗi không dùng bị loại khỏi file; chỉ giữ nhãn, định dạng, danh sách chọn, ghi chú, công thức tra cứu và sheet danh mục.
> Khi NSW/SGCL có mẫu mới: chạy lại công cụ này rồi chạy bộ kiểm thử.

## 0. Khác biệt của mẫu HQ_NHAP so với mẫu cũ

| Nội dung | Mẫu cũ | Mẫu HQ_NHAP (đang dùng) |
|---|---|---|
| Số sheet | 21 | **20** – bỏ `InlandAttachmentList`; `Cargo manifest` (ẩn) đứng trước `Passenger list` |
| DG manifest cột E | Proper shipping name | **Cty vận chuyển / Transporter's name** |
| GD B33/B34, NOA B32, ConfirmationOfArrival B10 | công thức liên kết ngoài | **giá trị** → hệ thống ghi Ngày ký / Người ký |
| Passenger list B3–B5, Empty Container B3–B5 | giá trị | công thức lỗi `#REF!` → đã thay bằng ô trống (B5 = CN01) |
| Crew list | dòng mẫu 11 | dữ liệu tới dòng 29 + vùng phụ E30:E48 (ngày sinh) → đã làm sạch |
| Ship Security | 1 dòng cảng | **10 dòng cảng ghé** (A25:E34) + vùng phụ C36:D45 |

**Quy ước khai báo rút ra từ file thực tế (đã áp dụng làm mặc định):**
Họ = `-`, Tên = họ tên đầy đủ · B4 ghi năm · cảng ghi mã UN/LOCODE (B6 cảng trước, B7/B8 = cảng đến) · DO/FO/FW chỉ ghi số ·
B14–B19 ghi 1/0 theo bản khai có kèm · hàng rời: loại cont `Other`, đơn vị TNE/MTQ · ô không có thông tin trong file thực tế ghi `NIL`
(hệ thống **không** tự ghi NIL – để trống và liệt kê cho nhân viên).


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
| Q1 | ~~Họ/Tên~~ – **đã rõ** từ file HQ_NHAP: Họ = "-", Tên = họ tên đầy đủ | Mặc định theo file thực tế; vẫn có tùy chọn khác |
| Q2 | B3 Số hồ sơ / B4 Năm đăng ký: do NSW cấp hay đại lý tự điền? | Để trống (có ô nhập ở Tùy chọn xuất file) |
| Q3 | ~~Ngày ký/Người ký~~ – **đã rõ**: mẫu mới là giá trị | Ghi từ Tùy chọn xuất file |
| Q4 | Mã cảng (UN/LOCODE) cho Goods Declaration P/R, DG B6/B7: lấy từ danh mục nào? | Lấy mã 5 ký tự có trong chứng từ; nếu không có → ghi nguyên văn + cảnh báo, nhân viên nhập mã |
| Q5 | “List of House bill of lading”: làm sao phân biệt House B/L và Master B/L trong bộ chứng từ của SGCL? | Chưa điền, chỉ xóa mẫu |
| Q6 | B14–B19 GD/NOA (“số bản” các bản khai kèm theo): ghi số lượng bản hay 1/0? | Để trống, nhập tay nếu cần |
| Q7 | Goods Declaration: 1 dòng / container hay 1 dòng / B/L khi 1 B/L có nhiều container? Cột V “Loại cont” bắt buộc nhưng chứng từ thường không ghi 20/40/45 | 1 dòng / dòng manifest. Cột V: tự nhận diện từ chứng từ (20GP/40HC/45HC, mã ISO 22G1/45G1/L5G1, cột Size/Type); thiếu thì nhân viên chọn ở tab Hàng hóa |
| Q8 | Sheet ẩn “Cargo manifest” có còn dùng không? | Giữ ẩn, chỉ xóa mẫu |
| Q9 | Bảng chất thải (A38:C43) và nhóm hàng C1_XEP/C2_DO… (A46:G51) cần phân loại theo danh mục NSW – quy tắc phân loại của SGCL? | Chưa điền (không tự suy đoán) |
| Q10 | B5 Chức năng chứng từ ở các sheet không có dữ liệu: giữ `CN01` hay để trống? | Ghi giá trị chọn ở Tùy chọn (mặc định `CN01`) cho mọi sheet |

| Q11 | Có muốn hệ thống tự ghi `NIL` vào các ô bắt buộc không có thông tin (như file thực tế)? | Để trống + liệt kê |
| Q12 | List of House B/L: file thực tế khai cả B/L thường (Master = House). Có muốn tự điền mỗi B/L một khối? | Chưa điền |


## Quy ước đã được SGCL xác nhận
- GD/NOA nhóm hàng, cột "Loại hàng": **3 = Hàng lỏng (mã tên hàng LIQ..)**, **9 = Hàng container (CON..)**, **12 = Hàng khô / hàng rời khô (DRY..)**.
- Phân nhóm: C2_DO = hàng nhập khẩu dỡ tại cảng đến; C5 = hàng quá cảnh không xếp dỡ (ghi "HÀNG DỠ TẠI ..." ở Mô tả).
- Chức danh thuyền viên và đơn vị ở Ship's store ghi đúng như chứng từ (không đổi mã).
- Hành lý thuyền viên không có gì phải khai: NIL. Loại container không có trong chứng từ: Other.
- List of House bill of lading: mỗi B/L một khối, số B/L ghi cả ô số vận đơn và số vận đơn gốc.
- Goods Declaration: hàng rời → Tổng số kiện B6 = 0, Loại kiện B7 = NE (Declaration list cột O); Notify tìm trong mọi chứng từ của cùng B/L (kể cả "Bên thông báo:" trong ô Consignee), không có thì = Consignee; Net weight không ghi = Gross; Kích thước/thể tích không ghi = 0; Đơn vị thể tích = MTQ; Cảng giao hàng/cảng đích (U) = Cảng dỡ hàng (P).
- List of House bill of lading: Notify như Goods Declaration; Loại hàng (N) theo danh mục "Loại hàng hóa": 9 container, 3 hàng lỏng, 10 hàng rời khô (BREAKBULK, như file HQ_NHAP); Ngày phát hành vận đơn = Ngày phát hành vận đơn gốc = "Place and date of issue" trên B/L; Ngày khởi hành = ngày "Shipped on board".
