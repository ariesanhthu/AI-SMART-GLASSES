# AI Smart Glass

AI Smart Glass là hệ thống kính thông minh hỗ trợ người dùng quan sát môi trường bằng giọng nói. ESP32-CAM hoặc camera trên thiết bị cung cấp ảnh; web app nhận lệnh nói, gửi ảnh và yêu cầu tới backend AI, sau đó hiển thị hoặc đọc kết quả.

## Tính năng

- Kích hoạt luồng điều khiển bằng câu gọi "bạn ơi".
- Mô tả cảnh vật và nhận diện đối tượng trong ảnh.
- Đếm hoặc tìm một đồ vật theo yêu cầu.
- Đọc văn bản trong ảnh (OCR).
- Lưu và truy vấn lịch sử yêu cầu.
- Trả kết quả tiếng Việt hoặc tiếng Anh.
- Chụp ảnh từ camera thiết bị, ESP32-CAM hoặc Supabase Storage.

## Kiến trúc

```text
Camera / ESP32-CAM
        |
        v
Frontend (Next.js) ---> Backend (FastAPI)
        |                    |
        |                    +-- Groq: intent, OCR, biên tập, dịch
        |                    +-- Hugging Face: phát hiện đối tượng
        |                    +-- BLIP / CLIP: mô tả và tìm vật
        v
Hiển thị + TTS
```

```text
AI-SMART-GLASSES/
├── Backend/
│   ├── app/
│   │   ├── main.py             # Routes và điều phối request
│   │   ├── config.py           # Cấu hình, đường dẫn, biến môi trường
│   │   ├── text.py             # Chuẩn hóa câu và phân loại intent
│   │   └── services/           # Groq, vision và lịch sử
│   ├── tests/                  # Unit/API tests
│   ├── be.py                   # Entrypoint tương thích
│   └── requirements.txt
├── Frontend/                   # Next.js 15, React 19, TypeScript
└── Edge-ESP/                   # Firmware và camera server ESP32
```

## Yêu cầu

- Python 3.10 trở lên.
- Node.js 20 trở lên.
- Git (dependency CLIP được cài trực tiếp từ GitHub).
- Khoảng trống đĩa đủ cho Torch, BLIP và CLIP. Model local được tải trong lần dùng đầu tiên.
- Tùy chọn: board ESP32-CAM và Arduino IDE/PlatformIO nếu chạy firmware.

## Cài đặt backend

```powershell
cd Backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Cập nhật `Backend/.env`:

| Biến | Bắt buộc | Mục đích |
| --- | --- | --- |
| `GROQ_API_KEY` | Có cho Groq | Phân loại intent, OCR, biên tập và dịch |
| `HF_API_TOKEN` | Có cho detect/count | Gọi Hugging Face Inference API |
| `GROQ_MODEL` | Không | Ghi đè model Groq mặc định |
| `GROQ_OCR_MODEL` | Không | Ghi đè model vision OCR |
| `CAPTION_MODEL` | Không | Ghi đè model BLIP local |
| `CORS_ORIGINS` | Không | Danh sách origin, phân tách bằng dấu phẩy |
| `MAX_UPLOAD_MB` | Không | Giới hạn ảnh upload, mặc định 10 MB |
| `KEEP_UPLOADS` | Không | Đặt `true` để giữ ảnh sau xử lý |

Chạy API:

```powershell
python be.py
```

API chạy mặc định tại `http://localhost:5000`; Swagger UI ở `http://localhost:5000/docs`.

## Cài đặt frontend

```powershell
cd Frontend
npm ci
```

Tạo `Frontend/.env.local` nếu dùng Supabase/TTS:

```dotenv
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
ZALO_AI_TTS_APIKEY=
```

Khởi động frontend:

```powershell
npm run dev
```

Mở `http://localhost:3000`, vào phần cài đặt và đặt Backend URL là `http://localhost:5000/analyze`.

## API chính

### `POST /analyze`

Request dạng `multipart/form-data`:

| Field | Kiểu | Mô tả |
| --- | --- | --- |
| `file` | image | Ảnh JPG, PNG hoặc WebP |
| `prompt` | string | Yêu cầu của người dùng |
| `language` | `vi` hoặc `en` | Ngôn ngữ phản hồi, mặc định `vi` |

Ví dụ:

```powershell
curl.exe -X POST http://localhost:5000/analyze `
  -F "file=@Backend/tests/fixtures/ocr.png" `
  -F "prompt=đọc chữ trong ảnh" `
  -F "language=vi"
```

Response:

```json
{
  "status": "success",
  "intent": "ocr",
  "file": "ocr.png",
  "text": "Nội dung nhận diện được."
}
```

Health checks: `GET /` và `GET /ping`.

## Kiểm tra

```powershell
cd Backend
python -m pytest -q

cd ..\Frontend
npm run lint
npm run build
```

## ESP32-CAM

Firmware nằm trong `Edge-ESP/`. `Edge-ESP/ESP/` cung cấp camera HTTP server và BLE Wi-Fi provisioning; các sketch Supabase là phương án upload ảnh trực tiếp. Không commit Wi-Fi password hoặc service key: đặt chúng trong file `secrets.h` cục bộ (đã được `.gitignore`).

## Bảo mật

- `.env`, cache, upload, lịch sử runtime và build output đã được loại khỏi Git.
- Token từng xuất hiện trong lịch sử Git cần được thu hồi và tạo lại; chỉ thêm token mới vào `.env`.
- Supabase anon key có thể xuất hiện ở client, nhưng vẫn phải cấu hình Row Level Security và Storage policies phù hợp.
