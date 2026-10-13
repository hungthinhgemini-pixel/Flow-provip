# Flow ProVip

Tool desktop (PySide6) tạo **ảnh / video hàng loạt bằng Google Flow** trên **nhiều tài khoản Google, chạy nhiều luồng**,
**khớp ảnh với voice** (Whisper tự nhận diện lời thoại + timestamp) và **xuất draft CapCut** để mở chỉnh sửa/export.

## Tính năng

| Tab | Chức năng |
|---|---|
| **Tài khoản** | Thêm nhiều tài khoản, mỗi tài khoản 1 profile trình duyệt riêng. Đăng nhập thủ công 1 lần (không lưu mật khẩu), hoặc nạp cookie JSON. Proxy riêng từng tài khoản. Bật/tắt tài khoản. |
| **Tạo hàng loạt** | Dán danh sách prompt (mỗi dòng 1 prompt, hoặc CSV `prompt,video_prompt`). Chọn: Tạo ảnh / Text → Video / Ảnh → Video. Ảnh tham chiếu để giữ nhân vật đồng nhất. Chạy lại riêng mục lỗi. |
| **Voice → CapCut** | ① Chọn file voice → Whisper chia thành phân cảnh 3–8s theo câu. ② Sửa/dán prompt cho từng cảnh rồi tạo ảnh/video. ③ Xuất draft CapCut: ảnh/video đặt đúng thời điểm voice, hiệu ứng zoom chậm, track voice, phụ đề. |
| **Cài đặt** | Số luồng / tài khoản, model, tỉ lệ khung, prompt chung trước/sau, model Whisper, độ dài cảnh, thư mục draft CapCut… |

**Đa luồng:** mỗi tài khoản chạy `số luồng / tài khoản` tác vụ song song, tất cả tài khoản lấy việc từ một hàng đợi chung.
Tài khoản hết quota / mất đăng nhập sẽ tự dừng và tác vụ được chuyển sang tài khoản khác. Lỗi khác được thử lại.

## Cài đặt

Cần Python 3.10+, [FFmpeg](https://ffmpeg.org/download.html) (có `ffprobe` trong PATH) và Google Chrome.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
playwright install chromium      # dự phòng nếu máy không có Chrome
python -m flowprovip
```

Windows: có thể bấm đúp `run.bat`.

## Cách dùng nhanh

1. **Tài khoản → + Thêm tài khoản → chọn dòng → Đăng nhập.** Cửa sổ Chrome hiện ra, đăng nhập Google, mở được
   Flow thì đóng cửa sổ. Trạng thái chuyển `ok`. Lặp lại cho từng tài khoản.
2. **Tạo hàng loạt:** dán prompt → `Tạo danh sách` → `▶ Bắt đầu`. Kết quả ở `output/images`, `output/videos`.
3. **Voice → CapCut:** chọn voice → `① Phân tích` → (tuỳ chọn) `Dán prompt theo cảnh` → `② Tạo` → `③ Xuất draft CapCut`
   → mở CapCut sẽ thấy project mới.

Mẹo prompt: lời thoại tiếng Việt dùng trực tiếp làm prompt cho kết quả chung chung. Nên copy cột lời thoại nhờ
ChatGPT/Claude viết prompt mô tả hình ảnh cho từng cảnh (1 dòng / cảnh), rồi dán vào bằng nút *Dán prompt theo cảnh*.
Đặt phong cách chung ở *Cài đặt → Prompt thêm phía trước/sau* để các cảnh đồng nhất.

## Lưu ý quan trọng

- **API của Flow là API nội bộ**, Google không công bố và có thể thay đổi. Toàn bộ URL/payload nằm trong
  `flowprovip/flow/endpoints.py`. Khi Flow đổi: mở Flow trên Chrome → F12 → Network → tạo thử 1 ảnh/video → so request
  tới `aisandbox-pa.googleapis.com` với file này và sửa (hoặc ghi đè qua `endpoint_overrides` trong `data/settings.json`).
  Tên model (`GEM_PIX`, `veo_3_1_t2v_fast`…) cũng lấy từ request thật trong tab Network.
- Flow dùng reCAPTCHA: nên để `headless = false` (chạy hiện trình duyệt). Chạy ẩn dễ bị từ chối.
- Tuân thủ điều khoản sử dụng của Google; dùng tài khoản của chính bạn. Chạy quá nhiều luồng / tài khoản trên cùng IP
  dễ bị giới hạn — dùng proxy riêng cho từng tài khoản nếu cần.
- **CapCut:** draft được ghi vào thư mục project mặc định của CapCut
  (Windows: `%LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft`). Một số bản CapCut mới mã hoá draft và có
  thể không đọc draft tạo bên ngoài; khi đó thử: tạo 1 project trống trong CapCut, đóng CapCut, chỉ đường dẫn thư mục
  đó ở *Cài đặt → Draft mẫu*. Mỗi draft kèm `subtitles.srt` để nhập phụ đề thủ công nếu cần.

## Cấu trúc code

```
flowprovip/
  accounts.py        quản lý tài khoản / profile / cookie
  config.py          cài đặt (data/settings.json)
  flow/endpoints.py  URL + payload API Flow (sửa ở đây khi Flow đổi)
  flow/client.py     phiên Flow cho 1 tài khoản (token, reCAPTCHA, tạo ảnh/video, tải về)
  engine.py          điều phối đa tài khoản × đa luồng, retry, chuyển tài khoản khi hết quota
  audio/transcribe.py  Whisper → câu + timestamp
  audio/scenes.py      chia phân cảnh, SRT
  capcut/draft.py      ghi draft CapCut
  pipeline.py        voice → cảnh → tác vụ → draft
  runner.py          chạy Playwright/engine ở luồng nền
  ui/                giao diện PySide6
tests/               pytest (engine với tài khoản giả, phân cảnh, draft)
```

Chạy test: `pip install -r requirements-dev.txt && pytest`
