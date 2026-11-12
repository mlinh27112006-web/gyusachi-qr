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
6a. **Tổng quan ca và báo cáo của Quản lý** (QLTT1, QLTT5): tổng quan realtime (bàn, đơn, doanh thu theo giờ, khách theo gói), checkout thay Thu ngân khi cần; báo cáo theo ca hoặc cả ngày (doanh thu từ hoá đơn đã thu, số đơn, số món không tính món huỷ, số khách và doanh thu theo gói)
6g. **Trang Admin** (ADM1 đến ADM4, `/admin/...`): tạo tài khoản cho mọi vai trò kể cả Chủ, sửa, khoá/mở khoá, **đặt lại mật khẩu**; tạo, đổi tên, xoá vai trò (chặn nếu còn tài khoản dùng) và **tích quyền cho từng vai trò** (các màn hình kiểm tra quyền mỗi lần vào); **sao lưu** thủ công hoặc tự động mỗi ngày, **phục hồi** từ bản đã chọn (có bản an toàn tự tạo trước, chạy trong một giao dịch), **dọn dẹp dữ liệu cũ** (xem trước, bắt buộc sao lưu trước khi xoá); xem **nhật ký thao tác** (lọc ngày, người làm, loại thao tác), **nhật ký lỗi** (theo mức độ), **nhật ký đăng nhập và đăng xuất**; cấu hình **máy in** và **tham số hệ thống** (thời gian hết phiên, số lần nhập sai tối đa, số phút được huỷ món)
6h. **Mọi người dùng** (XT1.3, XT1.4): tự **đổi mật khẩu** (bấm vào tên ở góc trên); **tự đăng xuất khi hết phiên** theo tham số của Admin; đăng nhập, đăng xuất, hết phiên đều được ghi nhật ký
6f. **Chủ quản trị nhân sự cấp cao và giám sát** (CHU3, CHU4): tạo, sửa họ tên, khoá/mở khoá tài khoản Quản lý (vai trò cố định là Quản lý) ở `/owner/managers`; xem toàn bộ dữ liệu kinh doanh ở chế độ **chỉ đọc** (hoá đơn, phiên bàn, món đã gọi, thực đơn, bàn, lịch ca, có lọc thời gian và phân trang) ở `/owner/data`; xem **nhật ký thao tác của Quản lý** theo tài khoản và khoảng ngày ở `/owner/logs`
6e. **Cấu hình kinh doanh của Chủ** (CHU2, trang `/owner/config`): cập nhật tên và địa chỉ nhà hàng (hiện trên màn khách, hoá đơn, báo cáo PDF); cài giờ mở cửa theo ngày trong tuần, mỗi ngày nhiều khung giờ, chọn nhanh Thứ 2–Thứ 6 hoặc cuối tuần; cài giá mỗi người của 6 gói buffet. Giá gói được chốt lúc mở bàn nên đổi giá không làm lệch bàn đang ăn hay hoá đơn cũ
6d. **Nhân sự và phân ca** (QLTT4, trang `/manager/staff` và `/manager/schedule`): tạo tài khoản Phục vụ/Bếp/Thu ngân (mật khẩu được mã hoá), sửa họ tên và vai trò, khoá hoặc mở khoá (tài khoản bị khoá thì phiên đang đăng nhập cũng hết hiệu lực); xếp ca theo ngày và giờ, giao bàn phụ trách cho Phục vụ, xem lịch theo tuần. Phục vụ thấy ca hôm nay và các bàn của mình được đánh dấu trên sơ đồ bàn
6b. **Quản trị menu** (QLTT2, trang `/manager/menu`): thêm, đổi tên, xoá nhóm món (chặn nếu còn món); thêm món kèm ảnh; sửa món; gán món vào "từ gói nào trở lên"; giới hạn số lượng tối đa mỗi lần gọi (từng món hoặc tất cả món); ẩn món hoặc cho bán lại. Mọi thay đổi ghi vào bảng `audit_logs`
6c. **Chủ nhà hàng** (CHU1, trang `/owner/reports`): doanh thu theo ngày/tuần/tháng/năm, thống kê theo gói buffet, món bán chạy, so sánh hai giai đoạn hoặc hai ca, **xuất báo cáo ra Excel hoặc PDF** (PDF có dấu tiếng Việt nhờ font đi kèm trong `app/static/fonts/`)
7. Đăng nhập, khoá tạm khi nhập sai nhiều lần, phân quyền theo mã quyền (XT1, một phần ADM1)

**Toàn bộ module trong tài liệu phân rã đã có bản chạy được.** Những điểm còn là hạn chế cần nhóm cân nhắc: (1) cấu hình máy in mới lưu thông số, nút in mã QR và hoá đơn vẫn dùng hộp thoại in của trình duyệt; (2) link QR dán cố định trên bàn, chưa có cơ chế gắn riêng cho từng lượt ngồi; (3) bản chạy phát triển của Flask chỉ để thử, triển khai thật cần gunicorn kèm eventlet/gevent; (4) chưa có kiểm thử tự động, hãy thử tay theo các kịch bản trong README.

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
python seed_demo.py     # (tuỳ chọn) dữ liệu demo 14 ngày để xem báo cáo

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
| quanly | 123456 | Quản lý | `/manager/overview` |
| admin | admin123 | Admin | `/manager/overview` |
| chu | 123456 | Chủ | `/owner/reports` |

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

## Thử trang Admin, đổi mật khẩu, hết phiên

> **Khi cập nhật từ bản trước (làm theo thứ tự):**
> 1. `flask --app run db migrate -m "them error_logs va login event"` rồi `flask --app run db upgrade` (thêm bảng `error_logs` và cột `login_logs.event`; một người làm rồi commit `migrations/`).
> 2. `python seed.py` để thêm hai quyền mới `CAN_VIEW_SYSTEM_LOGS`, `CAN_CONFIG_SYSTEM` (chỉ Admin có). Lần chạy này không ghi đè chỉnh sửa quyền của Admin.
> 3. Muốn **sao lưu/phục hồi**: máy chủ cần có `pg_dump` và `psql` (đi kèm PostgreSQL). Nếu chưa có trong PATH, đặt `PG_BIN_DIR` trong `.env` (xem `.env.example`).

1. Đăng nhập `admin` / `admin123` → **Tài khoản**: tạo một tài khoản Chủ, thử **đặt lại mật khẩu** cho `phucvu`, thử tự khoá chính mình (bị chặn).
2. **Vai trò và quyền**: tạo vai trò "Kế toán", tích quyền "Xem tổng quan ca và báo cáo ca", tạo tài khoản dùng vai trò đó, đăng nhập thử: được đưa thẳng vào màn Tổng quan ca. Bỏ tích thì lần vào tiếp theo bị chặn (403). Thử xoá vai trò còn tài khoản: bị chặn.
3. **Cấu hình**: đặt "Thời gian hết phiên" là 5 phút, đăng nhập một tài khoản khác, đợi quá 5 phút rồi bấm bất kỳ liên kết nào: bị đưa về màn đăng nhập. Xem **Đăng nhập** ở Admin để thấy sự kiện "Hết phiên".
4. **Sao lưu**: bấm "Sao lưu ngay", tải file về, thử "Phục hồi" bản đó (gõ PHUC HOI). Thử đặt lịch tự động mỗi ngày.
5. **Dọn dẹp dữ liệu cũ**: nhập số tháng, bấm "Xem trước" để thấy sẽ xoá bao nhiêu dòng, rồi xác nhận (hệ thống sao lưu trước).
6. **Nhật ký thao tác / lỗi / đăng nhập**: chạy `python seed_demo.py` để có dữ liệu mẫu; lọc theo ngày, người làm, loại thao tác, mức độ. Lỗi 500 thật chỉ được ghi vào nhật ký lỗi khi chạy ở chế độ không debug (chế độ debug hiện trang lỗi chi tiết cho lập trình viên).
7. **Đổi mật khẩu**: đăng nhập bằng tài khoản bất kỳ, bấm vào họ tên ở góc trên, đổi mật khẩu.

## Thử phần Chủ: tài khoản Quản lý, dữ liệu, nhật ký

> **Quan trọng khi cập nhật từ bản trước:** phần này thêm quyền mới `CAN_MANAGE_MANAGERS` (chỉ Chủ và Admin có). Database đã có dữ liệu thì chạy lại `python seed.py`: nó sẽ **chỉ bổ sung** quyền còn thiếu (không nạp lại dữ liệu mẫu, không gỡ quyền nào). Không có bước này, trang `/owner/managers` sẽ báo 403.

1. Đăng nhập `chu` → **Tài khoản Quản lý**: tạo `quanly2`. Thử khoá nó: nếu `quanly2` đang đăng nhập ở cửa sổ khác thì bị đăng xuất ngay; mở khoá thì vào lại được.
2. Đăng nhập `quanly` (hoặc `quanly2`) làm vài thao tác: thêm món, xếp ca, ẩn món.
3. Quay lại `chu` → **Nhật ký Quản lý**: chọn từng Quản lý và khoảng ngày để xem các thao tác vừa làm.
4. **Dữ liệu**: chọn loại (hoá đơn, món đã gọi, lịch ca...) và khoảng ngày; màn này không có nút sửa hay xoá nào.
5. Kiểm tra phân quyền: đăng nhập `quanly`, gõ thẳng `/owner/managers`: phải bị chặn (403).

## Thử phần cấu hình kinh doanh

1. Đăng nhập `chu` → **Cấu hình**. Đổi tên nhà hàng: tên đổi ngay trên thanh trên cùng, màn đăng nhập, màn khách.
2. **Giá gói**: sửa giá gói 219K thành 239.000; tên gói tự thành “Buffet 239K”. Thử đặt gói cao rẻ hơn gói thấp: hệ thống chặn.
3. Mở một bàn bằng gói đó (đăng nhập `phucvu`), rồi đổi giá tiếp: hoá đơn của bàn vẫn tính theo giá lúc mở bàn.
4. **Giờ mở cửa**: thêm khung giờ cho một ngày đã có khung trùng giờ: bị chặn. Xoá hết khung của hôm nay: khách quét QR sẽ thấy “Nhà hàng chưa mở cửa”.

> Phần này thêm cột `package_price` vào bảng `table_sessions`. Nếu bạn đã chạy migration từ bản trước: `flask --app run db migrate -m "them package_price"` rồi `flask --app run db upgrade`. Phiên bàn cũ chưa có cột này vẫn tính theo giá gói hiện tại.

## Thử phần nhân sự và phân ca

1. Đăng nhập `quanly` → **Nhân sự**: tạo tài khoản `phucvu2` (Phục vụ, mật khẩu từ 6 ký tự), rồi thử sửa họ tên, đổi vai trò, **Khoá**. Đăng nhập `phucvu2` ở cửa sổ khác: bị khoá thì không vào được.
2. **Lịch ca**: xếp `phucvu2` ca 10:30–14:00 hôm nay, tick bàn B01, B02. Xếp thêm một ca trùng giờ cho cùng người, hoặc giao B01 cho Phục vụ khác trùng giờ: hệ thống báo lỗi và chặn.
3. Đăng nhập `phucvu` (đã có ca mẫu nếu chạy `seed_demo.py`): sơ đồ bàn hiện "Ca hôm nay của bạn" và nhãn "Của bạn" trên các bàn được giao.

Quy tắc: Quản lý chỉ quản được ba vai trò Phục vụ, Bếp, Thu ngân; không xếp ca cho ngày đã qua, ca không qua nửa đêm; chỉ Phục vụ mới được giao bàn.

> Phần này thêm bảng `shift_tables`. Nếu bạn đã chạy migration từ bản trước: `flask --app run db migrate -m "them shift_tables"` rồi `flask --app run db upgrade` (một người làm, commit thư mục `migrations/`).

## Thử phần báo cáo

Chạy `python seed_demo.py` (sau `seed.py`) để có 14 ngày hoá đơn mẫu, rồi:

1. Đăng nhập `quanly`: **Tổng quan ca** hiện số bàn, đơn, doanh thu hôm nay; **Báo cáo** chọn ngày và ca để xem doanh thu, số đơn, số món, khách theo gói.
2. Đăng nhập `chu`: **Doanh thu và thống kê** đổi loại kỳ (ngày/tuần/tháng/năm) và khoảng ngày; **So sánh** hai giai đoạn (mặc định: 7 ngày gần nhất so với 7 ngày trước đó); **Xuất báo cáo** chọn loại báo cáo và Excel hoặc PDF rồi tải về.
3. Đối chiếu: tổng doanh thu trong báo cáo ngày phải bằng tổng các hoá đơn ở báo cáo ca của ngày đó.

Cách tính (sửa ở một chỗ duy nhất là `app/reports.py`): doanh thu cộng hoá đơn **đã thu** theo giờ thu tiền; số đơn, số món **không tính món đã huỷ** (số món là tổng số phần); số khách gồm người lớn và cả hai nhóm trẻ em; ca là khung giờ mở cửa của ngày (ca 1 tính từ 00:00, mỗi ca kéo dài đến lúc ca sau bắt đầu).

## Thử phần quản trị menu

1. Đăng nhập `quanly`, vào **Menu**.
2. Thêm nhóm món "Tráng miệng", rồi thêm món "Kem matcha" (kèm ảnh, từ gói 349K, tối đa 2 phần/lần).
3. Mở menu khách ở bàn đã mở với gói 219K: món mới **không** hiện. Mở bàn với gói 349K trở lên: món hiện, và giỏ chặn gọi quá 2 phần.
4. Bấm **Ẩn** món đó: khách không thấy nữa; bấm **Bán lại** để hiện lại.
5. Thử xoá nhóm còn món: hệ thống báo lỗi và chặn.

Ảnh món lưu ở `app/static/uploads/menu/` (đã nằm trong `.gitignore`, không đẩy lên GitHub). Mỗi người trong nhóm tự có ảnh trên máy mình; khi triển khai thật nên lưu ảnh ở nơi dùng chung.

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
  manager/         QLTT1 (tổng quan), QLTT2 (menu), QLTT3 (bàn + QR), QLTT4 (nhân sự, phân ca), QLTT5 (báo cáo)
  admin/           ADM1–ADM4 (tài khoản, vai trò và quyền, sao lưu, nhật ký, cấu hình)
  admin_service.py nghiệp vụ Admin   backup.py sao lưu/phục hồi bằng pg_dump/psql   scheduler.py lịch sao lưu
  owner/           CHU1 (báo cáo, so sánh, xuất Excel/PDF), CHU2 (cấu hình), CHU3 (tài khoản Quản lý), CHU4 (dữ liệu, nhật ký)
  audit.py         nhật ký thao tác (nguồn chung cho CHU4.2 và ADM3.1) + tên thao tác tiếng Việt
  reports.py       toàn bộ truy vấn báo cáo + quy ước tính số liệu
  exporters.py     tạo file Excel và PDF
  templates/, static/css/theme.css (nền đen, đỏ son)
```

Thêm vai trò mới (Admin): tạo thư mục `app/admin/` với `routes.py` có `bp = Blueprint("admin", __name__, url_prefix="/admin")`, đăng ký trong `app/__init__.py`, rồi thêm vào `HOME_BY_ROLE` ở `app/auth/routes.py`.

**Quy tắc code chung:**
- Nghiệp vụ viết trong `services.py`; route chỉ gọi hàm rồi trả trang/JSON.
- Phân quyền dùng `@perm_required("CAN_...")`, không viết `if role == ...` rải rác.
- Đổi cấu trúc bảng: sửa `models.py` → `flask --app run db migrate -m "mo ta"` → `flask --app run db upgrade` → commit cả thư mục `migrations/`.

## Chạy kiểm thử tự động

Bộ kiểm thử (thư mục `tests/`) dùng **pytest** và database **SQLite trong bộ nhớ**, nên không cần PostgreSQL và không đụng vào dữ liệu thật.

```powershell
pip install -r requirements-dev.txt
pytest
```

Bộ kiểm thử bao phủ các quy tắc quan trọng: tính tiền (công thức, giá chốt lúc mở bàn, hoá đơn đã thu không sửa), menu theo gói và giới hạn số lượng, giờ mở cửa, huỷ món trong thời hạn và Bếp quyết định, trình tự trạng thái món, trùng giờ và trùng bàn khi phân ca, ma trận phân quyền qua giao diện (ai vào được trang nào, không leo thang đặc quyền), khoá tài khoản và khoá tạm do nhập sai, hết phiên, đổi mật khẩu, bảo vệ Admin cuối cùng, dọn dẹp dữ liệu cũ, sao lưu theo lịch, các báo cáo (doanh thu chỉ tính hoá đơn đã thu, chia ca, số đơn không tính món huỷ, so sánh) và nhật ký.

Chạy một nhóm hoặc một test: `pytest tests/test_billing.py`, `pytest -k huỷ`, `pytest -x` (dừng ở lỗi đầu tiên). Đồng hồ trong kiểm thử được giả lập (mặc định Thứ 4 11/11/2026 12:00, đang trong ca trưa) nên kết quả không phụ thuộc giờ chạy thật.

Phần **không** có kiểm thử tự động: sao lưu và phục hồi thật bằng `pg_dump`/`psql` (cần PostgreSQL), gửi thông báo realtime qua SocketIO, giao diện trên trình duyệt thật, in ấn. Hãy thử tay các phần này theo các kịch bản ở trên.

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
