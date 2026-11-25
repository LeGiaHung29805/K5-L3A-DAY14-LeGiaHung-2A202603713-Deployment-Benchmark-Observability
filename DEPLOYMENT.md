# Deployment — agent Part 6

## Trạng thái

Đã hoàn thiện và kiểm chứng local: **PASS 12/12, 43/43 checks passed**. [Báo cáo đầy đủ](reports/part6_full_check.txt), [kiểm tra Compose](reports/part6_compose_smoke.json), [kiểm tra đồng thời/ngân sách](reports/part6_shared_limits_tests.txt).

**Chưa triển khai cloud, chưa có public URL hoặc ảnh dashboard.** Hai file cấu hình đã sẵn sàng; đây là hướng dẫn thực hiện CP6. LLM dùng mock nên không cần API key OpenAI. Chọn một nền tảng để triển khai chính.

## Bước 1 — Đưa bản hoàn thiện lên GitHub

**Mục đích:** Lưu source và bằng chứng bằng commit có thể đối chiếu, để Railway lấy đúng phiên bản Part 6 đã kiểm chứng.

**Trạng thái local đã kiểm tra ngày 25/11/2026:**

| Nội dung | Kết quả |
|---|---|
| Branch | `main`, theo dõi `origin/main` |
| Remote origin | `https://github.com/LeGiaHung29805/K5-L3-Day14-LeGiaHung-2A202603713-Deployment-Agent-Benchmark-Observability.git` |
| HEAD lúc kiểm tra | `83e677f` — `docs: align CHECKPOINTS Exercise 3.3 with RUBRIC (#2)` |
| Bản hoàn thiện | Source/config có thay đổi; tài liệu và reports còn untracked. Chưa có file staged tại thời điểm kiểm tra. |
| Secret local | `.env` được ignore, danh sách tracked không thấy `.env` thật. |
| Push bản hoàn thiện | Chưa xác nhận. Chưa thực hiện commit/push thay. Remote có cấu hình không chứng minh code mới đã lên GitHub. |

Chạy từng nhóm trong **Ubuntu WSL**, dừng lại nếu có lỗi.

**1. Vào gốc repository và kiểm tra đích push:**

```bash
cd /mnt/e/Lab_VinUni/Day14/K5-L3-Day14-LeGiaHung-2A202603713-Deployment-Agent-Benchmark-Observability
git status -sb
git remote -v
git check-ignore 06-lab-complete/.env
```

Branch cần là `main`, origin trùng URL trong bảng. Lệnh cuối phải in `06-lab-complete/.env`. `.env.example` là file mẫu được phép đưa lên Git.

**2. Stage code/tài liệu/report và kiểm tra trước commit:**

```bash
git add -- 06-lab-complete MISSION_ANSWERS.md DEPLOYMENT.md reports
git diff --cached --stat
git diff --cached --name-only
git diff --cached --check
```

Danh sách cần có app, Docker/Compose, cấu hình Railway, tài liệu và reports. Không được có `.env`, `.env.local` hay secret thật. Nếu danh sách sai, dừng trước commit để xử lý. Lệnh `--check` không in gì khi không có lỗi whitespace.

**3. Tạo commit và push:**

```bash
git commit -m "Complete Part 6 production-ready agent and validation reports"
git push -u origin main
```

Nếu Git yêu cầu author identity, cấu hình bằng thông tin tài khoản của bạn, không ghi email vào báo cáo. HTTPS dùng token hoặc credential helper; mật khẩu đăng nhập GitHub không dùng cho Git push. Không gửi token vào chat. Xem [GitHub authentication](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github#authenticating-with-the-command-line). Nếu push bị từ chối do quyền hoặc remote có commit mới, giữ output để kiểm tra, không force-push.

**4. Xác nhận phiên bản trên GitHub:**

```bash
git log -1 --oneline
git status -sb
```

Mở [repository GitHub](https://github.com/LeGiaHung29805/K5-L3-Day14-LeGiaHung-2A202603713-Deployment-Agent-Benchmark-Observability), chọn `main`; đối chiếu commit mới và các file `06-lab-complete/app/main.py`, `06-lab-complete/railway.toml`, `reports/part6_full_check.txt`.

Gửi output push, mã commit mới và `git status -sb` để ghi kết quả thực tế. Xác nhận GitHub xong mới chuyển sang Railway dưới đây.

## Bước 2 — Railway: deploy qua GitHub

Mục đích: đưa đúng agent Part 6 lên HTTPS public, nối Redis nội bộ và kiểm tra cấu hình cloud.

1. Review thay đổi và đưa code lên repository GitHub của bạn. Giữ `.env` ngoài Git; chỉ đưa `.env.example`. Chọn đúng branch chứa bản hoàn thiện.
2. Trong Railway, tạo project từ GitHub repo. Kiểm tra gói dùng thử/miễn phí và chi phí trước khi tạo tài nguyên, theo `RULES.md`; nếu yêu cầu thẻ mà bạn không muốn nhập, trao đổi với Lab Coach.
3. Tại service ứng dụng, đặt **Root Directory**: `/06-lab-complete`. Đặt **Railway Config File**: `/06-lab-complete/railway.toml`. Hai đường dẫn là hai thiết lập riêng. Build bằng Dockerfile; không đặt Start Command ghi đè CMD.
4. Thêm Redis trong cùng project. Trong Variables của agent, tạo biến tham chiếu `REDIS_URL` đến `REDIS_URL` của service Redis, dùng mục Add Reference. Nếu tên service là `Redis`, giá trị tham chiếu là `${{Redis.REDIS_URL}}`; tên phải khớp service thực tế.
5. Sinh key riêng cho cloud bằng `python -c 'import secrets; print(secrets.token_urlsafe(32))'` trong Ubuntu rồi lưu vào Variables dưới đây. Đây là secret: không chụp màn hình hay đưa giá trị vào bài nộp.

| Biến của agent | Giá trị |
|---|---|
| `AGENT_API_KEY` | Key ngẫu nhiên vừa sinh |
| `REDIS_URL` | Reference tới Redis cloud |
| `ENVIRONMENT` | `production` |
| `REDIS_NAMESPACE` | `day14` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1` |
| `MONTHLY_BUDGET_USD` | `10` |
| `MAX_OUTPUT_TOKENS` | `500` |
| `LOG_LEVEL` | `INFO` |

6. Để Railway cấp `PORT`. Deploy/redeploy sau khi đặt biến, đọc build/runtime log. Trong Networking tạo domain public cho agent; Redis không cần domain public.
7. Dùng URL thật để chạy các lệnh kiểm tra bên dưới. `/health` 200 chỉ xác nhận process sống; phải có `/ready` 200 và `/ask` có key 200 để xác nhận Redis và request hoạt động.

Root Directory không tự đổi đường dẫn config Railway: [Build configuration](https://docs.railway.com/builds/build-configuration). Cách thêm Redis: [Railway Redis](https://docs.railway.com/databases/redis).

## Render: phương án thay thế

Mục đích: triển khai web và Key Value bằng Blueprint đã viết sẵn.

1. Đưa code lên GitHub, mở Render → New → Blueprint, chọn repo và branch.
2. Đặt **Blueprint Path** là `06-lab-complete/render.yaml`.
3. Review hai service `day14-agent` và `day14-cache`, cùng region Singapore. YAML đặt web `rootDir: 06-lab-complete`, Dockerfile `./Dockerfile`, context `.` tương đối với root đó. Web nhận `REDIS_URL` từ Key Value qua `fromService`.
4. Chọn gói phù hợp quy định lab và xem chi phí trước khi xác nhận tạo service. YAML không phải cam kết có gói miễn phí.
5. Blueprint sinh `AGENT_API_KEY` tự động. Sau khi deploy, đọc key trong Environment của web để dùng riêng ở terminal; không đưa vào báo cáo. Giữ CMD Docker và `PORT` do Render cấp.
6. Lấy HTTPS URL của web và chạy phần kiểm tra dưới đây.

Tham khảo [Blueprint path](https://render.com/docs/infrastructure-as-code), [cấu hình root và Docker context](https://render.com/docs/monorepo-support), [tham chiếu Key Value và secret](https://render.com/docs/blueprint-spec).

## Kiểm tra URL thật và lưu bằng chứng

Mục đích: xác nhận CP6 từ Internet, phân biệt liveness, readiness và auth. Chạy trong Ubuntu, từ thư mục `06-lab-complete/`, với venv đã kích hoạt:

```bash
mkdir -p ../reports
read -r -p 'Public HTTPS URL: ' LAB_BASE
LAB_BASE="${LAB_BASE%/}"
read -r -s -p 'AGENT_API_KEY tren cloud: ' LAB_API_KEY
echo
{
  printf 'health: '
  curl -sS -o /dev/null -w '%{http_code}\n' "$LAB_BASE/health"
  printf 'ready: '
  curl -sS -o /dev/null -w '%{http_code}\n' "$LAB_BASE/ready"
  printf 'missing key: '
  curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$LAB_BASE/ask" \
    -H 'Content-Type: application/json' -d '{"question":"Hello"}'
  printf 'valid key: '
  curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$LAB_BASE/ask" \
    -H 'Content-Type: application/json' -H "X-API-Key: $LAB_API_KEY" \
    -d '{"question":"What is deployment?"}'
} | tee ../reports/part6_cloud_http.txt
unset LAB_API_KEY
set -o pipefail
python check_production_ready.py --public-url "$LAB_BASE" \
  2>&1 | tee ../reports/part6_public_check.txt
```

Kỳ vọng bốn mã lần lượt **200, 200, 401, 200**. Đây là kỳ vọng, chưa phải kết quả đã chạy. Script `--public-url` chỉ thêm phép thử `/health` trên cloud; các kiểm tra còn lại của script vẫn chạy local. Vì vậy phải giữ cả report HTTP cloud.

Nếu `/ready` 503: kiểm tra Redis đã chạy, `REDIS_URL` reference đúng, cùng mạng/region và biến đã áp dụng sau redeploy. Nếu `/ask` 401: đối chiếu key của service cloud; nếu 429: đợi `Retry-After`; nếu 402: kiểm tra ngân sách và namespace. Log app là JSON, có request ID và status.

Sau khi chạy thành công, ghi public URL thật vào đầu file này, bổ sung mã HTTP thực nhận, ảnh dashboard đã che secret và cập nhật Part 3 trong `MISSION_ANSWERS.md`. Giữ dịch vụ hoạt động đến khi được chấm; sau đó dọn tài nguyên cloud theo yêu cầu lab. Part 7 Benchmark & Observability là phần tiếp theo của bài nộp, chưa nằm trong kết quả Part 6 này.
