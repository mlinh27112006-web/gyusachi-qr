# GYUSACHI: đặt món bằng mã QR

Bộ khung project cho đồ án **Hệ thống đặt món bằng mã QR và quản lý đơn hàng**, làm theo tài liệu phân rã chức năng (7 vai trò). Công nghệ: Python (Flask), PostgreSQL, Flask-SocketIO (cập nhật realtime), VSCode, GitHub.

## Bản khung này đã chạy được những gì

Luồng xương sống, từ đầu đến cuối:

1. **Phục vụ** mở bàn (chọn gói buffet, nhập số khách), hoặc gọi món hộ khách (PV1)
2. **Khách** quét QR bàn, chỉ thấy món thuộc gói của bàn, gọi món, theo dõi trạng thái, huỷ món trong 5 phút, gọi nhân viên (KH1 đến KH4)
3. **Bếp** nhận đơn realtime, bắt đầu làm, báo xong, duyệt/từ chối huỷ món, báo hết món (BEP1)
4. **Phục vụ** nhận thông báo "món sẵn sàng", yêu cầu thanh toán, đổi bàn, sửa số khách (PV1 đến PV3)
5. **Thu ngân** lập hoá đơn (giá gói × (người lớn + trẻ 1m–1m3 ÷ 2)), xác nhận thu tiền, checkout trả bàn (TN1, TN2)
6. **Quản lý** xem danh sách bàn, in mã QR, thêm bàn, khoá bàn (một phần QLTT3)
7. Đăng nhập, khoá tạm khi nhập sai nhiều lần, phân quyền theo mã quyền (XT1, một phần ADM1)

**Chưa có** (để nhóm làm tiếp): báo cáo và xuất Excel/PDF (QLTT1, QLTT5, CHU1), quản lý menu và nhân sự trên giao diện (QLTT2, QLTT4), cấu hình nhà hàng (CHU2), quản trị quyền, sao lưu, nhật ký (ADM1 đến ADM4), đổi mật khẩu. Bảng dữ liệu cho các phần này đã có sẵn trong `app/models.py`.

## Cài đặt (Windows)

Cần cài trước: Python 3.11+, PostgreSQL 16, Git, VSCode.

```powershell
# 1. Tạo database (trong SQL Shell psql hoặc pgAdmin)
#    CREATE DATABASE qr_order;

# 2. Môi trường ảo + thư viện
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Cấu hình
copy .env.example .env
#    mở .env, sửa MATKHAU và BASE_URL (IP máy trong mạng LAN, xem bằng ipconfig)

# 4. Tạo bảng + nạp dữ liệu mẫu
flask --app run db init
flask --app run db migrate -m "tao bang ban dau"
flask --app run db upgrade
python seed.py

# 5. Chạy
python run.py
```

Nếu PowerShell chặn kích hoạt venv: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
Trong VSCode: `Ctrl+Shift+P` → **Python: Select Interpreter** → chọn `.venv`.

> Lưu ý nhóm: thư mục `migrations/` (sinh ra ở bước `db init`) **phải commit lên GitHub**. Chỉ **một người** chạy `db init` và `db migrate` lần đầu rồi push; những người còn lại chỉ chạy `flask --app run db upgrade`.

## Tài khoản mẫu

| Tài khoản | Mật khẩu | Vai trò | Trang vào |
|---|---|---|---|
| phucvu | 123456 | Phục vụ | `/waiter/tables` |
| bep | 123456 | Bếp | `/kitchen/` |
| thungan | 123456 | Thu ngân | `/cashier/` |
| quanly | 123456 | Quản lý | `/manager/tables` |
| admin | admin123 | Admin | `/manager/tables` |
| chu | 123456 | Chủ | (chưa có màn) |

Đăng nhập tại `/login`. **Đổi hết mật khẩu mẫu** trước khi dùng thật.

## Thử luồng chính (khoảng 5 phút)

Mở 3 cửa sổ trình duyệt (hoặc 1 cửa sổ thường + 2 cửa sổ ẩn danh) để đăng nhập 3 vai trò cùng lúc.

1. Đăng nhập `quanly`, vào **Bàn và mã QR**, mở ảnh QR của bàn B01 (hoặc bấm vào link `/t/<token>`).
2. Đăng nhập `phucvu`, ở bàn B01 bấm **Mở bàn**: chọn gói, 2 người lớn, 1 trẻ 1m–1m3.
3. Mở link của bàn B01 trên điện thoại (cùng Wi-Fi) hoặc tab khác, vào **Xem menu**, gọi vài món, gửi đơn.
4. Đăng nhập `bep`: đơn hiện ra ngay, bấm **Bắt đầu làm** rồi **Xong, mang ra**. Bên Phục vụ và khách đều nhận thông báo.
5. Ở `phucvu` bấm **Yêu cầu thanh toán**; đăng nhập `thungan`, **Lập hoá đơn**, **Xác nhận đã thu**, **Checkout**. Bàn B01 trở lại trống.

Quy tắc đã cài sẵn để thử: gói thấp không thấy món của gói cao (ví dụ Bò Wagyu A5 chỉ từ gói 469K); ngoài giờ mở cửa khách không vào được; huỷ món chỉ trong 5 phút và chỉ khi bếp chưa làm; hoá đơn đã thu thì không sửa.

> Giờ mở cửa mẫu là 10:30–14:00 và 16:30–22:00 (Thứ 2 đến Thứ 6), 10:30–22:00 (Thứ 7, Chủ nhật). Khi thử ngoài giờ này, khách sẽ thấy "Nhà hàng chưa mở cửa". Muốn thử mọi lúc, tạm sửa giờ trong `seed.py` (hoặc sửa bảng `opening_hours` bằng pgAdmin).

## Cấu trúc

```
app/
  models.py        toàn bộ bảng (chốt chung cả nhóm)
  services.py      nghiệp vụ lõi: giờ mở cửa, kiểm tra giỏ, huỷ món, hoá đơn...
  permissions.py   @perm_required("CAN_...")
  events.py        SocketIO (phòng kitchen / waiter / cashier / session-<id>)
  auth/            XT1                (đăng nhập)
  customer/        KH1–KH4            (quét QR, menu, đơn, gọi nhân viên)
  waiter/          PV1–PV3
  kitchen/         BEP1
  cashier/         TN1–TN2
  manager/         QLTT3 (bàn + QR)   ← làm tiếp QLTT1, 2, 4, 5 tại đây
  templates/, static/css/theme.css (nền đen, đỏ son)
```

Thêm vai trò mới (Chủ, Admin): tạo thư mục `app/owner/` với `routes.py` có `bp = Blueprint("owner", __name__, url_prefix="/owner")`, đăng ký trong `app/__init__.py`, rồi thêm vào `HOME_BY_ROLE` ở `app/auth/routes.py`.

**Quy tắc code chung:**
- Nghiệp vụ viết trong `services.py`; route chỉ gọi hàm rồi trả trang/JSON.
- Phân quyền dùng `@perm_required("CAN_...")`, không viết `if role == ...` rải rác.
- Đổi cấu trúc bảng: sửa `models.py` → `flask --app run db migrate -m "mo ta"` → `flask --app run db upgrade` → commit cả thư mục `migrations/`.

## Đẩy lên GitHub

```powershell
git init
git add .
git commit -m "Khung project GYUSACHI"
git branch -M main
git remote add origin https://github.com/<ten-ban>/gyusachi.git
git push -u origin main
```

Kiểm tra trên GitHub **không có file `.env`** (đã được `.gitignore` chặn; chỉ có `.env.example`). Nếu lỡ commit `.env`, đổi ngay mật khẩu database.

Làm nhóm: mỗi người một nhánh (`git checkout -b feature/ten-nhanh`), commit nhỏ có ghi mã module (ví dụ `KH4.3: huỷ món trong 5 phút`), xong thì tạo Pull Request vào `main`.

## Khi chạy thật

Máy chủ của Flask chỉ để phát triển. Khi triển khai, chạy bằng `gunicorn` với `eventlet` hoặc `gevent` để SocketIO ổn định, đặt `SECRET_KEY` ngẫu nhiên, và `BASE_URL` là tên miền thật (các mã QR in ra phải in lại nếu đổi `BASE_URL`).
