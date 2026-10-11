# Prediction & Capacity Mode

Module `prediction-capacity-mode` chứa lõi thuật toán học máy dự báo nhu cầu và giải thuật tối ưu hóa năng lực điều độ kho 3 tầng DENSO.

---

## 1. Tổng Quan Kiến Trúc

Hệ thống được tổ chức thành 2 tầng xử lý liên hoàn:
- Tầng 1 (AI Forecasting): Sử dụng `HistGradientBoostingRegressor` dự báo nhu cầu Workload Inbound và Outbound theo các khung 1h, 3h và 12h, tích hợp cơ chế tự bù sai số thời gian thực (Online Adaptive Bias).
- Tầng 2 (Capacity Optimization): Mô phỏng dòng chảy kho 3 tầng (`simulate_24h`), quét điểm nghẽn và tìm kiếm phương án can thiệp tối ưu (san tải Heijunka, điều chuyển lao động, tăng ca OT, điều phối xe tự hành AMR).

---

## 2. Cấu Trúc File

| Tên File | Chức Năng |
| :--- | :--- |
| `prediction_model_final.py` | Kịch bản huấn luyện mô hình `HistGradientBoostingRegressor` trên tập dữ liệu năm 2026 và xuất các file artifact `.pkl`. |
| `inference_final.py` | Lớp `WarehouseForecaster` phục vụ suy luận thời gian thực, tích hợp bộ bù sai số thích ứng (Online Adaptive Bias), tính dải an toàn Upper 90% và khử nhiễu can thiệp Heijunka. |
| `capacity_model.py` | Lớp `CapacityModelEngine` mô phỏng động học 3 tầng kho, quét điểm nghẽn, chấm điểm phạt kịch bản và thực thi giải thuật tối ưu hóa điều phối. |
| `app.py` | Giao diện Streamlit độc lập phục vụ kiểm thử và đánh giá module dự báo và điều độ. |
| `model_inbound.pkl` | Trọng số mô hình dự báo Workload Inbound. |
| `model_outbound.pkl` | Trọng số mô hình dự báo Workload Outbound. |
| `model_features.pkl` | Danh sách các cột đặc trưng đầu vào tương ứng của mô hình. |
| `data/table_1_workload_inbound.csv` | Kết quả dự báo và năng lực Inbound qua 2.160 giờ kiểm thử 2027. |
| `data/table_2_workload_outbound.csv` | Kết quả dự báo và năng lực Outbound qua 2.160 giờ kiểm thử 2027. |
| `data/table_3_storage_inbound.csv` | Kết quả mô phỏng tồn kho sàn Inbound qua 2.160 giờ kiểm thử 2027. |
| `data/table_4_storage_buffer.csv` | Kết quả mô phỏng tồn kho Kitting Buffer qua 2.160 giờ kiểm thử 2027. |
| `data/table_5_storage_outbound.csv` | Kết quả mô phỏng tồn kho sàn Outbound qua 2.160 giờ kiểm thử 2027. |
| `README.md` | Tài liệu kỹ thuật của module. |


---

## 3. Tầng 1: Mô Hình Dự Báo AI (Forecasting Engine)

### Kỹ thuật tạo đặc trưng (Feature Engineering)
- Biến trễ (Lags): $t-1, t-2, t-3, t-4, t-12, t-18, t-24, t-72, t-168$.
- Trung bình trượt (Rolling Means): Cửa sổ 3h, 6h, 12h, 24h.
- Chỉ số biến thiên:
  - Tỷ lệ xung đột biến: `spike_ratio_1h_3h = (y_t-1 + 1) / (y_t-3 + 1)`.
  - Gia tốc biến thiên: `diff_1h_2h = y_t-1 - y_t-2`.
  - Đỉnh 24h: `rollmax_24h`.
  - Tỷ lệ so với mức nền: `(y_t-1 + 1) / (rollmean_6h + 1)`.
- Đặc trưng chu kỳ ca làm việc (Shift Patterns): Mã hóa 6 phân đoạn ca (ca đêm, chuyển giao sáng, cao điểm sáng, nghỉ trưa, cao điểm chiều, ca thường).

### Cơ chế bù sai số thích ứng (Online Adaptive Bias)
- Khung 1h: Bộ lọc Single EMA cập nhật theo sai số thực tế tại $t$:
  `Bias_1h = 0.40 * Error + 0.60 * Bias_1h` (kẹp biên [-35, 35]).
- Khung 3h: Kết hợp EMA tức thời với hệ số suy giảm `decay = max(0.4, 1.0 - step * 0.05)`.
- Khung 12h: Cập nhật Shift Bias theo từng mã ca làm việc `ShiftBias_s = 0.35 * Error + 0.65 * ShiftBias_s` (kẹp biên [-25, 25]).
- Khử nhiễu can thiệp con người (Zero Feedback Confounding): Khối lượng dời ca do điều độ được trừ ra khỏi số liệu thực tế trước khi tính sai số, giúp mô hình chỉ học biến thiên tự nhiên.

---

## 4. Tầng 2: Mô Phỏng Kho & Tối Ưu Năng Lực (Capacity Engine)

### Định mức chuẩn DENSO
- Năng lực bốc dỡ Inbound / Outbound: 15.0 pallets/người/giờ.
- Năng lực xe tự hành AMR: 14.0 pallets/xe/giờ (đội xe tối đa 8 xe).
- Trần sức chứa: Inbound 200 pallets, Buffer 500 khay/thùng, Outbound 300 pallets.
- Ngưỡng cảnh báo sớm (80%): Inbound 160 pallets, Buffer 400 khay/thùng, Outbound 240 pallets.

### Hàm mục tiêu chấm điểm phạt (Penalty Function)
`Total Penalty = 10.0 * Penalty_storage + 3.0 * Cost_action + 1.0 * Score_disruption`
- `Penalty_storage`: Vi phạm ngưỡng vàng phạt hệ số 1.0; vượt trần đỏ phạt hệ số 5.0.
- `Cost_action`: Chi phí tăng ca OT (1.5 * số công nhân * số giờ).
- `Score_disruption`: Mức độ xáo trộn do dịch chuyển đơn hàng hoặc điều chuyển nhân sự.

### 5 Chiến lược điều phối giải quyết điểm nghẽn
1. Micro-Heijunka Inbound: Kéo sớm đơn hàng về các ca trước đó (dời số lượng pallet nguyên).
2. Cross-dock Labor Dispatching: Điều động công nhân Outbound sang Inbound.
3. Shift Swap: Huy động công nhân từ ca thấp điểm cùng ngày sang ca cao điểm.
4. Overtime (OT): Bổ sung công nhân làm thêm giờ trong các khung xung tải cao.
5. AMR Buffer Relief: Điều động thêm xe AMR và lên lịch sạc bù tại các ca thấp điểm.

---

## 5. Hướng Dẫn Sử Dụng

### Huấn luyện lại mô hình AI:
```bash
python prediction-capacity-mode/prediction_model_final.py
```

### Khởi chạy giao diện thử nghiệm độc lập:
```bash
streamlit run prediction-capacity-mode/app.py
```
