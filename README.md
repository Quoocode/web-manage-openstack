# 🌩️ OpenStack Flask Dashboard

Ứng dụng web dùng **Flask (async)** để quản lý tài nguyên **OpenStack** như:
- Tạo/xóa Network, Router
- Tạo/xóa Instance
- Gán Floating IP cho Instance
- Scale tự động nhiều máy ảo
- Hiển thị thông tin hạ tầng qua giao diện web

---

## ⚙️ 1. Cấu hình môi trường OpenStack (mycloud)

Trước khi chạy, bạn cần cấu hình thông tin kết nối đến tài khoản **mycloud** trên OpenStack.

### 🔹 Bước 1: Đăng nhập vào Dashboard OpenStack
> https://cloud-compute.uitiot.vn/

### 🔹 Bước 2: Mở menu góc phải → chọn **“View Credentials”**

Bạn sẽ thấy các thông tin như:
OS_AUTH_URL=
OS_PROJECT_ID=
OS_PROJECT_NAME=
OS_USER_DOMAIN_NAME=
OS_PROJECT_DOMAIN_NAME=
OS_USERNAME=
OS_PASSWORD=
OS_REGION_NAME=

### 🔹 Bước 3: Tạo file `clouds.yaml`

Tạo file `clouds.yaml` trong đường dẫn:
- **Windows:** `%USERPROFILE%\.config\openstack\clouds.yaml`
- **Linux/macOS:** `~/.config/openstack/clouds.yaml`

Nội dung mẫu (thay các giá trị trong dấu `< >` bằng thông tin của bạn):

```yaml
clouds:
  mycloud:
    auth:
      auth_url: https://cloud-compute.uitiot.vn:5000/v3
      username: "<your-username>"
      password: "<your-password>"
      project_id: "<your-project-id>"
      project_name: "<your-project-name>"
      user_domain_name: "<your-user-domain>"
      project_domain_name: "<your-project-domain>"
    region_name: "RegionOne"
    interface: "public"
    identity_api_version: 3
🧩 2. Cài đặt môi trường Python
Bước 1️⃣: Tạo môi trường ảo (venv)
python -m venv venv

Bước 2️⃣: Kích hoạt môi trường ảo

Windows:

venv\Scripts\activate


Linux/macOS:

source venv/bin/activate

Bước 3️⃣: Cài đặt thư viện cần thiết
pip install -r requirements.txt


Nếu bạn dùng Flask async, cần thêm:

pip install "flask[async]"

🚀 3. Chạy ứng dụng Flask

Chạy lệnh:

python app.py


Mặc định Flask chạy ở:

http://127.0.0.1:5000/
