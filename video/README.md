# Video dựng bằng code (HyperFrames)

Thử nghiệm dựng hoạt hình người que theo phong cách "What if" bằng HTML + GSAP,
render ra MP4 bằng HyperFrames (Node 22, FFmpeg, Chrome Headless Shell).

```bash
cd video/stickman-test
npm run check     # kiểm tra
npm run render    # xuất MP4 vào thư mục renders/
```

`stickman-test/index.html`: một cảnh 12 giây (ruồi bay qua mặt, bắt ruồi, chớp trắng,
đóng băng khung hình, chữ lớn). GSAP nằm cục bộ ở `gsap.min.js` để render không cần mạng.
