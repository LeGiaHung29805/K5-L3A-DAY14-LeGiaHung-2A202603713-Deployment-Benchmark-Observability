# Deployment — agent Part 6

## URL và trạng thái

**Public URL:** [day14-agent-53c5ceff.up.railway.app](https://day14-agent-53c5ceff.up.railway.app)
**Platform:** Railway, project `precious-rebirth`, environment `production`, region US West (California), một replica ứng dụng và Redis riêng.
**GitHub:** [Repository L3A](https://github.com/LeGiaHung29805/K5-L3A-DAY14-LeGiaHung-2A202603713-Deployment-Benchmark-Observability), branch `main`. Repo đã được đổi tên và remote local đã cập nhật theo xác nhận.

Ngày 25/11/2026 đã deploy commit `7efa7d023eeb2c51df053a392f8dec1a9ed160ea` với history Redis, `/chat` và SSE. Deployment `433dbc32-d361-4e31-87d8-29571cb45d74` hiển thị **Active / Deployment successful**, agent và Redis **Online**. Kiểm tra HTTP lúc `2026-11-25T13:56:16Z` xác nhận bản mới hoạt động; không chỉ dựa vào nhãn Online.

## Cấu hình build và runtime

| Mục | Cấu hình |
|---|---|
| Source | Repository GitHub ở trên, `main`; Railway còn hiển thị tên cũ đã được GitHub redirect. Deployment mới lấy đúng commit `7efa7d0`. |
| Root Directory | `/06-lab-complete` |
| Build | Dockerfile trong thư mục Part 6, Python slim, multi-stage, non-root |
| Start | CMD Docker chạy `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}` với graceful timeout 5 giây |
| Public networking | Domain HTTPS trỏ tới port `8080`, đúng cổng Uvicorn trên Railway |
| Healthcheck | `/health`, đã lưu và apply trên dashboard |
| Redis | Service `Redis` cùng project/environment, có `redis-volume`; ứng dụng dùng reference `${{Redis.REDIS_URL}}` |
| Restart | On Failure, tối đa 10 lần theo giới hạn plan hiện tại |
| Auto deploy | Dashboard hiển thị unavailable; lần triển khai mới thực hiện bằng Apply/Deploy, xác nhận commit thực tế sau deploy. |

`railway.toml` và `render.yaml` được giữ cho hợp đồng bài lab và cách triển khai tương ứng. Dashboard hiện thông báo Config as Code đã deprecated, không cho service chưa từng dùng opt in từ 28/08/2026; cấu hình cũ được hỗ trợ đến 01/12/2026. Vì vậy không coi việc khai báo đường dẫn TOML trong hướng dẫn trước là bằng chứng Railway đã áp dụng file. Cấu hình thực tế của service được kiểm tra/lưu trên dashboard. Tham chiếu: [Railway Config as Code](https://docs.railway.com/config-as-code).

Lần build đầu lỗi `go.mod file not found` vì chọn Dockerfile Go ở gốc repo. Đã sửa Root Directory về Part 6. Dockerfile Go trùng lặp ở gốc được bỏ; ví dụ gốc vẫn nằm trong `02-docker/multi-stages/`. Không sửa script chấm hoặc golden dataset.

## Biến môi trường đã đặt

Chỉ liệt kê tên/giá trị cấu hình công khai; không ghi API key hoặc URL Redis chứa mật khẩu.

| Biến | Giá trị/phương thức |
|---|---|
| `AGENT_API_KEY` | Secret riêng của service, giá trị được che |
| `REDIS_URL` | Reference tới `Redis.REDIS_URL` trong project |
| `PORT` | `8080` |
| `ENVIRONMENT` | `production` |
| `LOG_LEVEL` | `INFO` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1` |
| `MONTHLY_BUDGET_USD` | `10` |
| `MAX_OUTPUT_TOKENS` | `500` |

History dùng default trong code: tối đa 50 lượt hỏi–đáp/session, TTL 86400 giây từ lần ghi cuối. Rate limit và ngân sách dùng Redis, ngân sách theo ngày/tháng UTC. Không dùng key LLM trả phí vì agent gọi mock.

## Kết quả kiểm tra API public

Mục đích: xác nhận liveness, readiness với Redis, bảo vệ API và xử lý request qua HTTPS.

| Phép thử | HTTP thực nhận | Nội dung chính |
|---|---:|---|
| `GET /health` | 200 | `{"status":"ok"}` |
| `GET /ready` | 200 | `{"ready":true}` |
| `POST /ask` thiếu key | 401 | `Missing or invalid API key` |
| `POST /ask` có key hợp lệ | 200 | Có answer, cost, session ID và `storage="redis"` |
| `GET /history/{session_id}` có key | 200 | Hai message sau request đầu |
| `POST /chat` cùng session | 200 | Message count tăng lên 4 |
| `POST /ask/stream` cùng session | 200 | Nhận nhiều event SSE và event done, message count 6 |
| Đọc lại history sau stream | 200 | Đủ 6 message trong Redis |

Bằng chứng gốc: [JSON HTTP cloud](reports/part6_cloud_http.json), [bốn kết quả CP6](reports/part6_cloud_http.txt). Response headers được lưu; request header chứa key không được ghi vào report. Kết quả trước khi cập nhật code được giữ trong `reports/diagnostics/part6_cloud_initial.json` để phân biệt hai phiên bản.

### Lệnh kiểm tra lại từ Ubuntu

Các lệnh sau để tái hiện kết quả, không chứa secret trong tài liệu. Nhập key đang dùng trên Railway khi được nhắc:

```bash
BASE_URL=https://day14-agent-53c5ceff.up.railway.app
curl -i "$BASE_URL/health"
curl -i "$BASE_URL/ready"
curl -i -X POST "$BASE_URL/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is deployment?"}'
read -rsp 'Railway API key: ' LAB_API_KEY; echo
curl -i -X POST "$BASE_URL/ask" \
  -H "X-API-Key: $LAB_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is deployment?"}'
unset LAB_API_KEY
```

Mã kỳ vọng theo thứ tự: **200, 200, 401, 200**. Tối đa 10 request/phút/key; nếu đã thử nhiều lần, đợi theo `Retry-After` khi nhận 429 rồi kiểm tra tiếp. Không đưa key vào URL hoặc commit file môi trường.

## Kiểm chứng local và phần mở rộng

- [Chấm đầy đủ Part 6 kèm public URL](reports/part6_public_check.txt): **PASS 12/12, 44/44 checks**, SIGTERM hoàn tất request và exit 0, Docker stop 0.6 giây, image 63 MB theo script. [Lần local trước đó](reports/part6_full_check.txt) có 43/43 checks, stop 0.5 giây.
- [Bảy test Redis](reports/part6_extensions_tests.txt): PASS, gồm atomic rate/budget, rollover, idempotency, ownership/retention/TTL và ghi history đồng thời.
- [Smoke Nginx ba agent](reports/part6_extensions_smoke.json): thấy đủ ba backend, history dùng chung và còn sau restart; rate limit cũng còn sau restart. Đây là kiểm chứng local; Railway chỉ chạy một replica.
- [GitHub Actions quality gate](https://github.com/LeGiaHung29805/K5-L3A-DAY14-LeGiaHung-2A202603713-Deployment-Benchmark-Observability/actions/runs/45635693939): **success**, accuracy 100%, không regression. [Log CI](reports/ci_quality_gate.txt).

Phần mở rộng đáp ứng yêu cầu tự học: history trong Redis, SSE và load balancing Nginx. Rubric của chương trình không có điểm bonus riêng. SSE hiện chia câu trả lời mock đã tạo xong thành event, chưa phải streaming trực tiếp từ nhà cung cấp LLM. Chi phí và history được quyết toán trước khi bắt đầu stream; client ngắt giữa chừng không hoàn lại lượt/chi phí. History lưu hội thoại, mock chưa dùng toàn bộ history làm context.

## Ảnh bằng chứng

- [Dashboard deploy](screenshots/dashboard.png).
- [Service đang chạy](screenshots/running.png).
- [Kiểm tra API](screenshots/test.png).

Service cloud được giữ hoạt động để chấm; chỉ xóa sau khi được chấm theo RULES. Đã dừng các stack Docker lab local bằng `down -v` sau khi lưu đủ bằng chứng: [Part 6 cleanup](reports/part6_cleanup.txt), [Part 7 cleanup](reports/part7_cleanup.txt), [dọn file trùng/cache](reports/cleanup_manifest.json). Không thay đổi tiến trình riêng đang lắng nghe cổng 8000.
