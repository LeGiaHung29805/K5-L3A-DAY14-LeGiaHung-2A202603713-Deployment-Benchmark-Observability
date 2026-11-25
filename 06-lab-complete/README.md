# Part 6 — Final Project: Production-ready AI Agent

Agent đã hoàn thiện từ bản khung, kết hợp Part 1–5: FastAPI, API key, Redis dùng chung, rate limit, ngân sách ngày/tháng, log JSON và Docker.

Kết quả chấm đầy đủ: **PASS 12/12 — 43/43 checks passed**. Báo cáo ở [part6_full_check.txt](../reports/part6_full_check.txt), phần giải thích ở [MISSION_ANSWERS.md](../MISSION_ANSWERS.md#part-6-final-project--cp5).

Hướng dẫn chạy bản hiện tại: [SETUP.md](SETUP.md). Hướng dẫn deploy từng bước: [DEPLOYMENT.md](../DEPLOYMENT.md). Hiện đã kiểm chứng local; chưa triển khai cloud.

Bài chỉ được tính hoàn thành khi script chấm báo **`PASS 12/12`**:

```bash
pip install -r requirements.txt
python check_production_ready.py
```

---

## Checklist Deliverable

- [x] Dockerfile (multi-stage, < 500 MB)
- [x] docker-compose.yml (agent + redis)
- [x] .dockerignore
- [x] Health check endpoint (`GET /health`)
- [x] Readiness endpoint (`GET /ready`)
- [x] API Key authentication
- [x] Rate limiting
- [x] Cost guard
- [x] Config từ environment variables
- [x] Structured logging
- [x] Graceful shutdown
- [x] Public URL ready (Railway / Render config)

---

## Script chấm dựa vào những tiêu chí dưới đây

Script tự khởi động agent của bạn, gọi API thật, build và chạy Docker image. Để chấm được, agent phải tuân theo các quy ước sau:

| Hạng mục | Yêu cầu |
|----------|---------|
| Điểm vào | `app/main.py` có biến `app` (FastAPI), chạy được bằng `uvicorn app.main:app --workers 2` từ thư mục này |
| `GET /health` | Luôn trả **200** khi process còn chạy, kể cả khi Redis chưa kết nối được |
| `GET /ready` | **200** khi sẵn sàng; **503** khi Redis (`REDIS_URL`) không kết nối được |
| `POST /ask` | Body JSON `{"question": "..."}` (được phép có thêm `user_id`) → **200** |
| API key | Header `X-API-Key` phải trùng biến `AGENT_API_KEY`; thiếu hoặc sai → **401** |
| Rate limit | Tối đa `RATE_LIMIT_PER_MINUTE` request / 60 giây cho mỗi API key; vượt → **429** (nên có header `Retry-After`). State lưu trong **Redis**, vẫn còn sau khi restart agent |
| Cost guard | Tổng chi phí vượt `DAILY_BUDGET_USD` (hoặc `MONTHLY_BUDGET_USD`) → **402** |
| Biến môi trường | Đọc từ env: `AGENT_API_KEY`, `REDIS_URL`, `RATE_LIMIT_PER_MINUTE`, `DAILY_BUDGET_USD` / `MONTHLY_BUDGET_USD`, `PORT`, `ENVIRONMENT`. Liệt kê đủ trong `.env.example`. Script chạy với `ENVIRONMENT=staging` |
| Log | Mỗi dòng log của app là **1 JSON object hợp lệ** (log của uvicorn không tính) |
| Graceful shutdown | Nhận SIGTERM khi đang có request → request đó vẫn trả 200, process tự thoát với exit code 0. Trong Docker, `docker stop` phải xong trong < 10 giây |
| Docker image | Multi-stage, base slim, user non-root, có `HEALTHCHECK`, < 500 MB. `CMD` lắng nghe theo biến `PORT` (mặc định 8000), uvicorn là PID 1. Container khởi động được khi **không có** Redis |
| Compose | Một service build từ `Dockerfile` + một service dùng image `redis:*`; agent có `REDIS_URL` trỏ tới service Redis và `depends_on` nó |
| `.dockerignore` | Loại trừ `.env`, `__pycache__`, `venv` |
| Deploy config | `railway.toml` (builder `DOCKERFILE`, `healthcheckPath = "/health"`) **hoặc** `render.yaml` (`type: web`, `healthCheckPath: /health`, secret dùng `generateValue` / `sync: false`) |

---

## Cấu trúc ứng dụng

```
06-lab-complete/
├── app/
│   ├── main.py           # Routes, log JSON, lifespan và xử lý /ask
│   ├── config.py         # Environment và .env, validation cấu hình
│   ├── auth.py           # X-API-Key → 401 khi thiếu/sai
│   ├── rate_limiter.py   # Sliding window dùng Redis Lua → 429
│   ├── cost_guard.py     # Giữ chỗ/quyết toán ngân sách UTC → 402
│   ├── redis_client.py   # Redis pool, timeout và readiness
│   └── history.py        # History Redis nguyên tử, TTL và giới hạn lưu
├── utils/mock_llm.py     # Mock LLM — có sẵn, không cần sửa
├── Dockerfile            # Multi-stage, non-root, healthcheck
├── docker-compose.yml    # Nginx + ba agent + Redis, volume persistence
├── nginx/nginx.conf      # Docker DNS, load balancing, không buffer SSE
├── .dockerignore         # Loại secret và môi trường host
├── .env.example          # Cấu hình mẫu không chứa key thật
├── railway.toml          # Docker build + healthcheck
├── render.yaml           # Docker web + Key Value nội bộ
├── tests/                # Kiểm tra Redis đồng thời và ngân sách
├── SETUP.md              # Hướng dẫn chạy local
├── requirements.txt      # Có sẵn
├── check_production_ready.py   # Script chấm — không sửa
└── benchmark-observability/    # Part 7 — làm sau khi xong Part 6
```

**Gợi ý thứ tự làm:** `/health` → `config.py` → log JSON → `auth.py` → `redis_client.py` + `/ready` → `rate_limiter.py` → `cost_guard.py` → graceful shutdown → `Dockerfile` + `.dockerignore` → `docker-compose.yml` → `railway.toml` / `render.yaml`. Hướng dẫn từng bước: [CODE_LAB.md — Part 6](../CODE_LAB.md#part-6-final-project-60-phút).

---

## Chạy local

```bash
source /home/acer/.venvs/day14/bin/activate
docker compose -p k5-day14-final up -d --build
curl -i http://localhost:18006/health
curl -i http://localhost:18006/ready
```

Cổng `18006` đã được đặt trong `.env` của máy này để tránh trùng cổng 8000. Clone mới cần tạo `.env`, sinh API key và chọn cổng theo [SETUP.md](SETUP.md).

---

## Chấm bài

```bash
python check_production_ready.py                 # chấm đầy đủ — cần Docker đang chạy
python check_production_ready.py --skip-docker   # chế độ nhanh khi đang làm (bỏ build image)
python check_production_ready.py --static-only   # chỉ đọc file, không chạy agent
python check_production_ready.py --public-url https://your-app.railway.app   # thêm kiểm tra URL đã deploy
```

- Kết quả in theo từng tiêu chí: ✅ đạt · ❌ chưa đạt · ⚠️ chưa kiểm tra được.
- **Chỉ PASS khi cả 12 tiêu chí ✅.** Mục ⚠️ (vd máy chưa bật Docker) cũng tính là chưa đạt, nên khi nộp bài phải chạy chế độ đầy đủ.
- Lần đầu chạy, script build Docker image nên mất vài phút. Bài test stateless cần Redis: script dùng `REDIS_URL` nếu có, không thì tự bật container `redis:7-alpine` tạm thời.

---

## Deploy

Đã deploy tại [domain Railway](https://day14-agent-53c5ceff.up.railway.app), kiểm chứng `/health`, `/ready`, `/ask` thiếu/có key lần lượt 200/200/401/200 và các endpoint mở rộng. Cấu hình thực tế và raw ở [DEPLOYMENT.md](../DEPLOYMENT.md). Tiêu chí “Public URL ready” của script chấm chỉ xác nhận cấu hình; bằng chứng HTTP cloud được lưu riêng.

---

## Part 7 — Benchmark & Observability

Agent đã chạy được, bước tiếp theo là đo xem nó **nhanh** và **đúng** tới đâu, rồi **giám sát** khi chạy thật:

```bash
cd benchmark-observability
```

| Thư mục | Nội dung |
|---------|----------|
| `develop/` | Agent có `/metrics`, load test (p50/p95/p99, SLO), eval trên golden dataset + quality gate |
| `production/` | Docker Compose: agent x2 + Nginx + Prometheus + Grafana + Jaeger + Locust, 4 alert rules |

Hướng dẫn đầy đủ: [benchmark-observability/README.md](benchmark-observability/README.md). Nộp kèm `BENCHMARK_REPORT.md` theo [mẫu](benchmark-observability/BENCHMARK_REPORT_TEMPLATE.md).
