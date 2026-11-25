# Benchmark & Observability Report — Day 14

**Họ tên:** Lê Gia Hưng — 2A202603713 — L3A
**Ngày chạy:** 25/11/2026 (GMT+7). Timestamp trong JSON dùng UTC.
**Môi trường:** Ubuntu 24.04 trên WSL2, Python 3.12.3, kernel 6.18.58.1, Docker Desktop 29.7.2; Docker có 12 CPU logic, 12.43 GB RAM (11.57 GiB). Mỗi agent Part 7 bị giới hạn 0.5 CPU/256 MB, một worker. Chi tiết: [part7_environment.json](reports/part7_environment.json).

Các phép đo chạy trên máy dùng chung với trình duyệt; giai đoạn benchmark develop còn trùng thời gian tải Docker image. Đây là kết quả của phiên lab này, không phải phép đo cách ly tài nguyên. Các câu trả lời dùng mock LLM; cost là mô phỏng, không phải hóa đơn dịch vụ LLM.

Các bảng load/eval/scaling và chaos chính được đo trước khi bổ sung histogram độ dài câu hỏi của Exercise 7.1; phần kiểm chứng metric và lượt Exercise 7.4 thực hiện sau đó. Việc bổ sung metric không thay KB hay golden dataset. Không thay số của các lượt trước bằng số từ lượt chụp ảnh bổ sung.

## 1. SLO của agent

| SLI | SLO | Lý do |
|---|---|---|
| p95 latency `/ask` trong load test develop | < 500 ms | Ngưỡng có sẵn trong `load_test.py`, đánh giá độ trễ đa số request thành công. |
| Error rate `/ask` develop | < 2% | Phân biệt lỗi mock mặc định 1% với mức suy giảm đáng kể. |
| Accuracy trên golden dataset | ≥ 80% ban đầu; 100% sau sửa KB | Gate mặc định cho so sánh ban đầu; yêu cầu 23/23 và không regression khi hoàn thiện. |

Alert production dùng ngưỡng riêng của đề: error rate > 5% trong 1 phút, p95 > 1 giây trong 2 phút, cost > 2 USD/giờ trong 2 phút, instance down trong 30 giây. SLO develop và ngưỡng alert production không đồng nhất; không dùng trạng thái alert để thay kết luận load-test SLO.

## 2. Benchmark hiệu năng — develop

Mỗi lần gửi 300 request bằng `load_test.py`, `MOCK_ERROR_RATE=0.01`, `MOCK_SLOW_RATE=0.03`. Latency trong JSON chỉ tính response thành công; RPS và error rate tính toàn bộ request. Lệnh, cấu hình, exit code được lưu trong [manifest baseline](reports/part7_local_baseline_manifest.json).

### 2.1. Concurrency vs latency — agent v2

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---:|---:|---:|---:|---:|---|
| 1 | 4.30 | 192.9 | 228.1 | 1682.0 | 1.00% | PASS |
| 10 | 36.23 | 192.1 | 225.3 | 1694.8 | 1.67% | PASS |
| 50 | 98.28 | 221.1 | 400.5 | 1731.4 | 1.00% | PASS |
| 100 | 53.86 | 481.1 | 3675.4 | 3992.9 | 0.00% | FAIL: p95 |

Nguồn: [c1](reports/load_v2_c1.json), [c10](reports/load_v2_c10.json), [c50](reports/load_v2_c50.json), [c100](reports/load_v2_c100.json).

RPS tăng đến concurrency 50 rồi giảm ở 100; không tăng tuyến tính. Khi tăng số request cùng lúc, contention, scheduling, client và tài nguyên WSL cùng ảnh hưởng thời gian phục vụ. Kết quả cho thấy phiên chạy ở c100 vượt khả năng giữ SLO, nhưng chưa đủ dữ liệu CPU/queue theo thời điểm để quy nguyên nhân cho một thành phần duy nhất. Không thể coi error rate 0% là đạt khi p95 đã vượt ngưỡng.

### 2.2. Tail latency

Giữ concurrency 20, 300 request/lần, error rate cấu hình 1%; chỉ đổi `MOCK_SLOW_RATE`.

| MOCK_SLOW_RATE | avg (ms) | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|
| 0 | 441.5 | 873.5 | 897.4 |
| 0.03 | 524.1 | 1010.5 | 1813.0 |
| 0.1 | 474.6 | 1733.2 | 2012.0 |

Nguồn: [slow 0](reports/load_v2_slow_0.json), [slow 0.03](reports/load_v2_slow_0.03.json), [slow 0.1](reports/load_v2_slow_0.1.json), [manifest](reports/part7_local_slow_manifest.json).

p99 phản ánh nhóm request chậm rõ nhất: tăng từ 897.4 lên 1813.0 ms ngay ở tỷ lệ 3%, trong khi average tăng ít hơn. Đến 10%, p95 cũng đi vào nhóm chậm. Average không tăng đơn điệu trong phiên chạy này vì mẫu ngẫu nhiên và tải nền thay đổi; cả ba lần đều trượt SLO p95 500 ms. Dùng average làm SLO có thể che trải nghiệm xấu của một nhóm người dùng. Cần lặp nhiều lần trên máy cách ly để kết luận năng lực hệ thống, không sửa số đo cho giống kỳ vọng lý thuyết.

## 3. Benchmark chất lượng

Eval trên nguyên bộ 23 câu của đề. Tắt lỗi ngẫu nhiên (`MOCK_ERROR_RATE=0`) để so chất lượng câu trả lời; dữ liệu golden không thay đổi.

| Chỉ số | Agent v1 | Agent v2 ban đầu | Agent v2 sau sửa KB |
|---|---:|---:|---:|
| Câu đúng | 1/23 | 21/23 | 23/23 |
| Accuracy | 4.35% | 91.30% | 100.00% |
| Avg tokens/câu | 56.6 | 109.3 | 118.1 |
| Tổng cost (USD) | 0.000397 | 0.000764 | 0.000829 |
| Cost/câu đúng (USD) | 0.00039735 | 0.00003639 | 0.00003603 |
| p95 (ms) | 182.7 | 221.3 | 221.9 |
| Quality gate | FAIL (min 80%) | PASS (min 80%) | PASS (min 100%, 0 regression) |

Nguồn: [v1](reports/eval_v1.json), [v2](reports/eval_v2.json), [v2 fixed](reports/eval_v2_fixed.json). Cost/câu đúng lấy trực tiếp trường trong JSON; tổng cost được report làm tròn nên chia hai số hiển thị có thể lệch chữ số cuối.

| ID thiếu kiến thức ban đầu | Keyword thiếu | Sửa KB |
|---|---|---|
| security-02 | token, hết hạn, chữ ký | Thêm mục JWT: token có chữ ký, kiểm tra chữ ký, hạn dùng, issuer và audience. |
| scaling-03 | cpu, memory, custom metrics | Thêm mục HPA: scale replica theo CPU, memory hoặc custom metrics. |

Chỉ sửa `KNOWLEDGE_BASE` trong bản develop rồi đồng bộ sang production; không sửa bộ câu hỏi/keyword. v2 tốn nhiều token và chậm hơn v1 do có context, nhưng chi phí cho một câu đúng thấp hơn. Sửa KB tăng tổng cost 0.000764 → 0.000829 USD, đồng thời đưa độ đúng 21 → 23 câu. Keyword accuracy chỉ kiểm tra bộ câu hỏi cố định, không chứng minh agent trả lời đúng mọi câu ngoài bộ này.

Chạy v1 đối chiếu baseline v2 tạo **20 regression, exit code 1**: [eval_v1_regression.json](reports/eval_v1_regression.json), [output](reports/eval_v1_regression.txt). Workflow [Agent quality gate](.github/workflows/quality-gate.yml) chạy eval v2 với min accuracy 100% và baseline v2, chặn CI khi quality gate thất bại. Run GitHub Actions [45635693939](https://github.com/LeGiaHung29805/K5-L3A-DAY14-LeGiaHung-2A202603713-Deployment-Benchmark-Observability/actions/runs/45635693939) trên commit `f838597` đã **success**, accuracy 100%, 0 regression; [log gốc](reports/ci_quality_gate.txt), [trạng thái job](reports/ci_quality_gate.json).

Exit code 1 làm bước eval và job thất bại. Để bắt buộc chặn merge trên GitHub, cần đặt job `evaluate` thành required status check trong branch protection/ruleset; chỉ thêm workflow chưa tự thiết lập chính sách merge này.

## 4. Observability stack — production

Project Compose riêng `k5-day14-observability`: Nginx, 3 agent, Prometheus, Grafana, Jaeger và Locust. Chỉ publish các cổng local trên `127.0.0.1`. `/metrics` của agent chỉ dùng trong mạng Docker; gọi qua Nginx trả 404 như cấu hình. [Smoke API](reports/part7_stack_smoke.json), [targets](reports/part7_targets.json), [promtool SUCCESS](reports/part7_promtool.txt).

### Exercise 7.1 — loại metric và cardinality

- Counter: `http_requests_total`, tăng khi hoàn tất request; `llm_tokens_total` cộng token theo model/type.
- Gauge: `agent_in_flight_requests`, tăng khi nhận và giảm khi hoàn tất request, có thể tăng hoặc giảm.
- Histogram: `http_request_duration_seconds` xuất bucket/count/sum để ước lượng percentile; metric mới `agent_question_length_chars` đo độ dài bằng ký tự, bucket 20/50/100/200/500/1000/2000 và +Inf, không tạo label theo độ dài.

Đã thêm histogram vào cả develop và production, observe một lần khi request hợp lệ vào endpoint `/ask`, trước retrieval/LLM. Phép thử câu hỏi dài **40 ký tự** ghi count **1**, sum **40**. Ba URL lạ đều 404 và được gom vào đúng một label `route="unmatched"`, counter bằng **3**; không tạo ba series route mới. Nếu dùng URL thật làm label, bot có thể tạo vô số series theo URL, gây tăng cardinality và tốn RAM/storage. [Raw metrics](reports/part7_question_metrics.prom), [kết quả](reports/part7_question_metrics.json).

Smoke metric chạy server develop riêng rồi gửi SIGTERM: log có application shutdown complete, launcher trả -15; phép thử này không dùng để chứng minh graceful exit 0 của Part 6. Hợp đồng shutdown Part 6 được kiểm riêng trong report chấm đầy đủ.

### Exercise 7.4 — đọc dashboard và trả lời bốn câu hỏi

Đo bổ sung với **hai agent**, **30 users**, **ramp 5 users/giây**, chạy 120 giây; model small, v2, error rate 1%, slow rate 3%. Snapshot PromQL tại **14:24:31 UTC**, sau 75 giây tải: [JSON gốc và biểu thức query](reports/part7_exercise_7_4_metrics.json), [log Locust](reports/part7_exercise_7_4_locust.txt), [ảnh dashboard](screenshots/exercise-7.4-dashboard.png), [ảnh theo instance](screenshots/exercise-7.4-instances.png).

1. **p95 và avg bao nhiêu, khoảng cách có nghĩa gì?** p95 `/ask` **294.13 ms**, average **232.09 ms**, chênh **62.04 ms**. p95 là ước lượng từ histogram bucket của cửa sổ một phút, avg lấy sum/count trong cùng cửa sổ; bao gồm các status được middleware đo. Nhóm request chậm làm tail cao hơn average. Với xác suất slow 3%, p95 có thể vẫn ở nhóm nhanh, trong khi p99 cao; không suy rằng mọi request đều nhanh từ p95 tốt. Số hiển thị trên ảnh vài giây sau có thể khác snapshot JSON vì dashboard refresh liên tục.
2. **Nginx chia đều cho hai instance không?** Snapshot `/ask`: `172.19.0.8:8000` **9.65 req/s**, `172.19.0.5:8000` **9.52 req/s**, xấp xỉ **50.35% / 49.65%**. Phân phối gần đều trong cửa sổ đo, không khẳng định mọi thời điểm đều đúng 50/50. Manifest ghi hai container thực. Đường thứ ba trong đồ thị 15 phút là lịch sử lượt ba agent trước đó; snapshot query và bảng version hiện tại chỉ còn hai.
3. **Vì sao input tokens/s lớn hơn output?** Input **1530.57 token/s**, output **825.10 token/s** trong snapshot. v2 thêm context retrieval vào prompt, còn câu trả lời mock ngắn hơn tổng prompt. Panel Tokens/s dùng đồ thị stacked: đường biên trên có thể là input + output, không đọc vị trí đường cao hơn như giá trị riêng của output. Không coi quan hệ input > output là quy luật bắt buộc với mọi ứng dụng.
4. **Gọi `/metrics` qua localhost:8080 trả gì, vì sao?** **404**, được xác nhận trong [smoke](reports/part7_stack_smoke.json). Nginx có `location = /metrics { return 404; }` để không lộ thông tin vận hành qua cổng public. Prometheus scrape trực tiếp `agent:8000/metrics` trong mạng Compose nên vẫn thu được metric. Histogram mới trong production đã được scrape, count tổng ở snapshot là **1319**.

### 4.1. Ảnh chụp thực tế

- [x] [Grafana đang có tải](screenshots/grafana-dashboard.png).
- [x] [Jaeger: trace chậm và span LLM](screenshots/jaeger-slow-trace.png).
- [x] [Jaeger: trace 503 có event exception](screenshots/jaeger-error-trace.png).
- [x] [Prometheus: hai alert firing đồng thời](screenshots/prometheus-alert-firing.png).

Ảnh Grafana và Prometheus chính chụp trong thí nghiệm AB, kết hợp error 20% và slow 30%. Các ảnh bổ sung từng thí nghiệm được chụp ở lượt riêng; số thời gian trong bảng sau lấy từ lượt đo đầu tiên.

| Lượt bổ sung | Dashboard | Alerts | Raw lượt chụp |
|---|---|---|---|
| A | [Dashboard A](screenshots/experiment-A-dashboard.png) | [Error firing](screenshots/experiment-A-alerts.png) | [JSON A](reports/part7_experiment_A.json) |
| B | [Dashboard B](screenshots/experiment-B-dashboard.png) | [Latency firing](screenshots/experiment-B-alerts.png) | [JSON B repeat](reports/part7_experiment_B_repeat.json) |
| C | [Dashboard C](screenshots/experiment-C-dashboard.png) | [Cost firing](screenshots/experiment-C-alerts.png) | [JSON C repeat](reports/part7_experiment_C_repeat.json) |
| D | [Dashboard D](screenshots/experiment-D-dashboard.png) | [Instance down](screenshots/experiment-D-alerts.png) | [JSON D repeat](reports/part7_experiment_D_repeat.json) |
| E | [Dashboard E](screenshots/experiment-E-dashboard.png), [version v1](screenshots/experiment-E-version.png) | [Không alert](screenshots/experiment-E-alerts.png) | [JSON E repeat](reports/part7_experiment_E_repeat.json) |

Các ảnh không sửa nội dung/pixel để đổi kết quả; chỉ chuyển định dạng JPEG capture sang PNG để đúng tên file nộp. Panel `LLM cost (1h)` là tổng chi phí trong một giờ, khác panel `Cost burn rate (USD/giờ)` dự báo tốc độ chi tiêu mà alert C sử dụng.

### 4.2. Thí nghiệm phá hệ thống

Mỗi thí nghiệm độc lập dùng 30 Locust users; trả các biến khác về mặc định trước khi đổi biến cần thử, tạo Prometheus mới để không lẫn cửa sổ metric của thí nghiệm trước. Poll trạng thái alert mỗi 5 giây. Cột thời gian tính **từ lúc bắt đầu lệnh thay cấu hình**, gồm setup/recreate và thời gian chờ firing; đó là lần poll đầu thấy firing, độ phân giải khoảng 5 giây. Không đổi rule để làm alert bật nhanh hơn.

| # | Thay đổi | Alert firing | Từ lệnh thay đổi → firing | Panel rõ nhất | Bằng chứng |
|---|---|---|---:|---|---|
| A | MOCK_ERROR_RATE=0.2 | AgentHighErrorRate | 97.58 s (12.48 + 85.1) | Error rate | [JSON A](reports/part7_experiment_A.json) |
| B | MOCK_SLOW_RATE=0.3 | AgentHighLatencyP95 | 153.66 s (13.56 + 140.1) | HTTP/LLM p95, p99 | [JSON B](reports/part7_experiment_B.json) |
| C | LLM_MODEL=mock-llm-large | LLMCostBurnRateHigh | 167.03 s (16.43 + 150.6) | Cost USD/giờ, model | [JSON C](reports/part7_experiment_C.json) |
| D | docker pause một agent | AgentInstanceDown | 60.78 s (15.38 + 45.4) | Instances up: 3 → 2 | [JSON D](reports/part7_experiment_D.json) |
| E | AGENT_VERSION=v1 | Không alert trong 100 s tải | Không quan sát firing | Version, retrieval hit ratio | [JSON E](reports/part7_experiment_E.json) |
| AB | Error 0.2 + slow 0.3 | Error + Latency | 97.25 s; 157.65 s | Error rate và p95 | [JSON AB](reports/part7_experiment_AB.json) |

Ở E, “không alert” chỉ áp dụng khoảng quan sát 100 giây, không phải khẳng định mọi alert sẽ không bao giờ bật. Eval ngay trên production v1 chỉ đúng **1/23**, gate exit code 1: [eval production v1](reports/eval_production_v1.json). Agent có thể trả HTTP 200 nhanh nhưng nội dung sai. Cần eval định kỳ, golden/canary queries, so regression trước deploy và đo phản hồi/chất lượng nội dung sau deploy. Metric hạ tầng không thay thế đánh giá chất lượng.

Pause giữ container trong DNS để Prometheus thấy target `up=0`; stop có thể xóa target khỏi discovery. Lỗi 504 do Nginx không được agent tính vào error counter; cần metric load balancer và synthetic checks bên ngoài. Container đã được unpause trong `finally` của script.

### 4.3. Debug bằng trace và log

Trace chậm nhất trong tập trả về với `duration_min=1.5s`, `search_depth=100` ở khoảng AB (không khẳng định chậm nhất toàn bộ lịch sử):

- Trace ID: `7ac5c4905cb4f915ed0268ef6f2eaff3`.
- Tổng thời gian: **1741.407 ms**, 4 span.
- Span `chat mock-llm-small`: **1659.437 ms**, chiếm **95.29%** thời gian trace. Nút thắt của request này nằm ở mock LLM.
- Trace lỗi: `f01e824ada23f68508d6d0eab1697413`, tổng **128.840 ms**, HTTP **503**, event `exception` chứa `utils.mock_llm.LLMError` và “Upstream LLM error: 503 Service Unavailable (mock)”.

Dòng log thật cùng trace ID:

```json
{"ts":"2026-11-25T13:40:05.694592+00:00","level":"INFO","service":"observable-agent","instance":"78a2e0952a59","event":"llm_call","trace_id":"7ac5c4905cb4f915ed0268ef6f2eaff3","span_id":"5b6208891d6ee40b","request_id":"1f85e68b29d8","model":"mock-llm-small","agent_version":"v2","input_tokens":81,"output_tokens":46,"cost_usd":4e-05,"llm_ms":1658.0}
```

Nguồn: [phân tích trace](reports/part7_trace_analysis.json), [trace chậm nguyên bản](reports/jaeger_slow_trace.json), [trace lỗi nguyên bản](reports/jaeger_error_trace.json), [log đối chiếu](reports/part7_trace_logs.json). `llm_ms` trong log đo khoảng bên trong lời gọi, không buộc bằng duration của span. `span_id` log mẫu hiện lấy từ context middleware; tương quan ở đây dựa vào **trace_id**, không coi nó là ID của span chat. Script xuất dùng search API v3 của Jaeger 2.23 và endpoint trace-by-ID, không sửa trace gốc.

## 5. Benchmark scaling — Locust

100 users, tăng 10 users/giây, 120 giây mỗi cấu hình. Bảng dùng riêng hàng **POST /ask** trong CSV, không dùng hàng Aggregated có cả `/health`. Locust có think time 0.5–2 giây và task `/ask`:`/health` = 10:1. Mock error rate 1%, slow rate 3%, model small.

| Instance | RPS `/ask` | p50 (ms) | p95 (ms) | p99 (ms) | Failures/requests |
|---|---:|---:|---:|---:|---:|
| 1 | 57.46 | 220 | 810 | 1800 | 78/6773 |
| 3 | 60.80 | 190 | 250 | 1700 | 65/7156 |

Nguồn: [scale_1_stats.csv](benchmark-results/scale_1_stats.csv), [scale_3_stats.csv](benchmark-results/scale_3_stats.csv), [manifest xác nhận số container trước/sau và ID backend](reports/part7_scaling_manifest.json). Locust exit code 1 ở các lần có mock 503 là kết quả lỗi request được lưu, không bị đổi thành PASS.

Scale 3 cải thiện p95 từ 810 xuống 250 ms (giảm khoảng 69.1%), RPS tăng khoảng 5.8%, p99 còn cao do mock slow request. Throughput không tăng 3 lần vì mô hình tải đóng có think time, cùng một máy host và upstream mock; đây không phải phép tìm RPS cực đại. Lần chạy đầu bị `compose run locust` khởi động dependencies và trả agent về mặc định hai replica, nên **không dùng** làm số liệu scaling. Raw của lần sai cấu hình được giữ trong [diagnostics](reports/diagnostics/replicas-defaulted-to-two/); đã chạy lại đúng 1/3 với `run --no-deps` và kiểm đếm container trước/sau.

## 6. Kết luận và câu hỏi thảo luận

Ba điều rút ra:

1. Phải đo latency, lỗi và chất lượng độc lập: HTTP 200 không chứng minh câu trả lời đúng; p95 đạt không chứng minh p99 tốt.
2. Metrics phát hiện xu hướng, trace xác định span chậm/lỗi, log có trace ID giúp tìm chi tiết; cần cả quan sát từ Nginx/client để tránh điểm mù.
3. Kết quả benchmark phụ thuộc mô hình tải và cấu hình thực tế. Cần giữ raw, kiểm replica và ghi tải nền; không dùng số của lần chạy sai hoặc sửa số để đạt SLO.

Nếu vận hành thật, bổ sung hàng đợi/in-flight requests, timeout/retry, saturation CPU/RAM, Redis latency/errors/eviction, chi phí và ngân sách theo kỳ, lỗi/latency Nginx, SSE disconnect, chất lượng theo nhóm câu hỏi và synthetic journey bên ngoài. Alert theo error budget burn rate và cảnh báo chi phí gần hết trước khi cost guard từ chối request.

**1. Dashboard xanh nhưng câu trả lời sai:** cần eval, regression gate và giám sát chất lượng nội dung như thí nghiệm E; golden signals không kiểm tra ngữ nghĩa.

**2. Vì sao Prometheus pull?** Scraper chủ động lịch lấy metric, quản lý target và suy ra `up` từ kết quả scrape. Service scale về 0 hoặc instance sống ngắn gây mất target/counter giữa các lần scrape; cần discovery phù hợp và export qua collector/managed monitoring hoặc cơ chế push hỗ trợ môi trường đó. Không giữ service luôn chạy chỉ để phục vụ scrape nếu nền tảng đã có cách thu metric phù hợp.

**3. Label user_id với 100.000 user:** cardinality tăng theo user nhân với route/status/method và các label khác; histogram còn nhân thêm bucket. Tăng RAM, storage và chi phí query. Không dùng user ID làm label metric; dùng log/trace có kiểm soát truy cập, hoặc nhóm hữu hạn.

**4. Sampling 10% trace:** giảm chi phí thu/lưu nhưng dễ bỏ sót lỗi hiếm và không xem được từng request. Head sampling ngẫu nhiên không bảo đảm giữ lỗi/chậm; tail sampling ưu tiên lỗi/chậm cần buffer và tài nguyên collector. Metric tổng vẫn cần thu độc lập, không tính error rate từ một tập trace thiên lệch.

**5. for: 0s và for: 30m:** 0s dễ báo động khi spike ngắn và gây nhiễu; 30m trì hoãn phát hiện sự cố, bỏ qua sự cố ngắn nhưng nghiêm trọng. Chọn cửa sổ theo SLO và thời gian phản ứng, kết hợp nhiều cửa sổ thay vì chỉ một ngưỡng.

Đã chuẩn bị script tái hiện trong [scripts/](scripts/). Chạy lại sẽ tạo kết quả mới theo trạng thái máy; lưu bản cũ trước khi thay report. Không force-push hoặc thay ngày commit.
