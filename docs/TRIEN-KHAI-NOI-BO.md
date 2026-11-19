# Triển khai SGCL trên mạng nội bộ với tên miền cố định

Mục tiêu: nhân viên trong công ty chỉ cần gõ **http://sgcl.local** (hoặc tên bạn chọn) trên trình duyệt là vào được web, không cần nhớ IP hay cổng.

Web chạy trên **1 máy chủ trong công ty** (máy tính để bàn bật 24/7, mini PC hoặc server). Dữ liệu và chứng từ tàu ở lại trong công ty, không đưa lên Internet.

---

## Bước 1. Chuẩn bị máy chủ

1. Chọn 1 máy luôn bật, cắm dây mạng LAN của công ty. Nên dùng Windows 10/11 hoặc Ubuntu, RAM 8GB trở lên.
2. Đặt **IP tĩnh** cho máy đó, ví dụ `192.168.1.50`. Có 2 cách: nhờ IT làm, hoặc vào trang quản trị router chọn "DHCP Reservation".
3. Cài **Docker**:
   - Windows: tải Docker Desktop tại https://www.docker.com/products/docker-desktop/
   - Ubuntu: `curl -fsSL https://get.docker.com | sh`

## Bước 2. Tải mã nguồn và chạy

```bash
git clone https://github.com/pchi111203-prog/sgcl-ship-docs.git
cd sgcl-ship-docs
docker compose up -d --build
```

Lần đầu mất khoảng 5–10 phút để tải và cài các phần cần thiết. Sau đó, mở trình duyệt **trên chính máy chủ** và vào `http://localhost` để kiểm tra.

- Dữ liệu (cơ sở dữ liệu, file tải lên, file xuất) nằm trong thư mục `sgcl-data/`. **Hãy sao lưu thư mục này định kỳ.**
- Web tự khởi động lại khi máy chủ khởi động lại.

## Bước 3. Tạo tên miền nội bộ

Chọn **một** trong các cách sau, tính theo `192.168.1.50` là IP máy chủ.

### Cách A: Khai báo trên router hoặc DNS công ty (khuyến nghị)

Vào trang quản trị router hoặc DNS nội bộ (ví dụ Windows Server DNS, pfSense, MikroTik), mục **Local DNS / Static DNS / Host**, rồi thêm:

```
sgcl.local  →  192.168.1.50
```

Sau đó mọi máy trong công ty đều vào được `http://sgcl.local` mà không cần cài thêm gì.

### Cách B: Khai báo file hosts trên từng máy nhân viên

Dùng khi router không có chức năng DNS. Trên **mỗi máy nhân viên**, mở file sau bằng quyền Administrator:

- Windows: `C:\Windows\System32\drivers\etc\hosts`
- macOS/Linux: `/etc/hosts`

Thêm dòng:

```
192.168.1.50   sgcl.local
```

### Đổi sang tên khác

Muốn dùng tên khác, ví dụ `chungtu.sgcl.vn` hoặc `sgcl.congty`:

1. Tạo file `.env` cạnh `docker-compose.yml` với nội dung `SGCL_DOMAIN=chungtu.sgcl.vn`
2. Chạy `docker compose up -d`
3. Khai báo tên đó ở Bước 3 thay cho `sgcl.local`.

## Bước 4. Bảo mật

1. Đăng nhập bằng `admin / admin123`, **đổi ngay mật khẩu** của `admin` và `staff`.
2. **Không** mở cổng 80/443 ra Internet trên router. Như vậy chỉ máy trong mạng công ty mới truy cập được.
3. Nhân viên làm việc từ xa nên kết nối VPN công ty (hoặc Tailscale) thay vì mở web ra Internet.

## Cập nhật phiên bản mới

```bash
cd sgcl-ship-docs
git pull
docker compose up -d --build
```

## Xử lý sự cố

| Hiện tượng | Cách xử lý |
| --- | --- |
| Gõ `sgcl.local` không vào được, nhưng gõ `http://192.168.1.50` vào được | Kiểm tra lại Bước 3 (DNS/hosts). Trên Windows chạy `ipconfig /flushdns`. |
| Không vào được cả bằng IP | Mở cổng 80 trên tường lửa của máy chủ (Windows Defender Firewall → Inbound Rules → Port 80). |
| Xem log lỗi | `docker compose logs -f sgcl` |
