# Chạy agent Part 6 trong Ubuntu WSL2

Mục đích: chạy cùng một bản agent đã chấm đạt với Redis, rồi kiểm tra health, readiness và xác thực trước khi deploy.

## Môi trường hiện tại

Python 3.12 trong `/home/acer/.venvs/day14`, dependencies đã cài. File `.env` local đã tạo với API key ngẫu nhiên và `HOST_PORT=18006`; file này được Git và Docker ignore. Stack kiểm chứng `k5-day14-final` đã được dừng, giữ volume Redis.

```bash
cd /mnt/e/Lab_VinUni/Day14/K5-L3-Day14-LeGiaHung-2A202603713-Deployment-Agent-Benchmark-Observability/06-lab-complete
source /home/acer/.venvs/day14/bin/activate
docker compose -p k5-day14-final up -d --build
docker compose -p k5-day14-final ps
curl -i http://localhost:18006/health
curl -i http://localhost:18006/ready
```

Hai endpoint đều phải trả 200. Đọc key vào biến shell mà không in ra terminal, rồi gọi API:

```bash
LAB_API_KEY="$(python -c 'from dotenv import dotenv_values; print(dotenv_values(".env")["AGENT_API_KEY"])')"
curl -i -X POST http://localhost:18006/ask \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $LAB_API_KEY" \
  -d '{"question":"What is deployment?"}'
unset LAB_API_KEY
```

Thiếu/sai key trả 401. Mặc định tối đa 10 request/60 giây cho mỗi API key; vượt giới hạn trả 429 cùng `Retry-After`. Request đã qua auth vẫn tính lượt kể cả khi sau đó ngân sách không đủ. Hết ngân sách hoặc không đủ phần giữ chỗ cho request tiếp theo trả 402. Redis lỗi trả 503 cho `/ready` và request cần Redis; `/health` vẫn 200.

## Clone mới hoặc cần tạo lại môi trường

Chạy từ thư mục Part 6. Không ghi đè `.env` đang dùng:

```bash
python3 -m venv /home/acer/.venvs/day14
source /home/acer/.venvs/day14/bin/activate
pip install -r requirements.txt
python - <<'PY'
from pathlib import Path
import secrets
path = Path('.env')
if not path.exists():
    text = Path('.env.example').read_text()
    text = text.replace('AGENT_API_KEY=', 'AGENT_API_KEY=' + secrets.token_urlsafe(32), 1)
    text = text.replace('HOST_PORT=8000', 'HOST_PORT=18006')
    path.write_text(text)
    path.chmod(0o600)
print('Local configuration ready; secret is not printed.')
PY
```

## Chạy Python trực tiếp

Mục đích: sửa code và xem log nhanh bằng Python trong venv, dùng Redis dành riêng cho dev trên cổng 16379. State dev này tách khỏi Redis của stack Compose.

```bash
docker compose -p k5-day14-final stop agent
docker run --rm -d --name day14-dev-redis \
  -p 127.0.0.1:16379:6379 redis:7-alpine
REDIS_URL=redis://127.0.0.1:16379/0 \
  uvicorn app.main:app --host 0.0.0.0 --port 18006 --timeout-graceful-shutdown 5
```

App nạp `.env`; biến môi trường đã đặt luôn được ưu tiên. Khi chạy Uvicorn trực tiếp phải chỉ định `--port`; `PORT` được Docker CMD sử dụng. Sau Ctrl+C, dùng `docker stop day14-dev-redis` để gỡ Redis dev; container này không có volume bền vững. Nếu cổng 16379 đang dùng, chọn cổng trống khác và đổi cả REDIS_URL.

## Chấm và dừng

```bash
set -o pipefail
python check_production_ready.py 2>&1 | tee ../reports/part6_full_check.txt
docker compose -p k5-day14-final logs --tail=50 agent
docker compose -p k5-day14-final down
```

Script chấm tự tạo Redis tạm khi không có `REDIS_URL` trong môi trường shell. `.env` của app không thay cấu hình Redis mà script chọn. Không export `REDIS_URL` trỏ tới stack chưa chạy trước khi chấm. `down` giữ named volume; chỉ thêm `-v` khi chủ động muốn xóa dữ liệu của project này.

Kiểm tra đồng thời/ngân sách có trong `tests/test_shared_limits.py`. Chỉ chạy với Redis dành riêng cho test:

```bash
TEST_REDIS_URL=redis://127.0.0.1:16379/0 \
  python -m unittest discover -s tests -v
```

Địa chỉ 16379 là ví dụ: cần khởi động Redis test có publish đúng cổng trước. Test dùng namespace ngẫu nhiên và chỉ xóa các key thuộc namespace đó.

## Phạm vi bản lab

LLM là mock; `cost_usd` là ước lượng với hai token/từ và đơn giá cố định trong code, không phải hóa đơn nhà cung cấp. Ngân sách chung theo namespace/môi trường, ngày/tháng UTC. Redis Lua giữ chỗ chi phí tối đa trước khi gọi mock và hoàn phần dư sau khi trả lời; sự cố process giữa hai bước có thể giữ khoản dự trù đến hết kỳ, nên giới hạn có thể bảo thủ. Các script hiện dùng Redis một node, chưa hỗ trợ Redis Cluster.

Đã kiểm tra 2 worker và restart agent. Volume/AOF bảo toàn dữ liệu local theo cấu hình; chưa đo failover, backup/restore hoặc tải production.
