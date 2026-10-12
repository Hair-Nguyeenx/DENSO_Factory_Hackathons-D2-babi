# Data Dictionary - Dữ Liệu Logistics DENSO

Tài liệu này định nghĩa cấu trúc, mục đích và đặc tả kỹ thuật của toàn bộ dữ liệu trong thư mục `data/`, phục vụ bài toán dự báo nhu cầu và điều độ dòng chảy kho 3 tầng.

---

## 1. Cấu Trúc Thư Mục Data

```
data/
|-- DATA_DICTIONARY.md                    # Tài liệu từ điển dữ liệu (File này)
|-- input/                                # Dữ liệu đầu vào và script phát sinh
|   |-- data_generator.py                 # Script mô phỏng dòng chảy logistics Pull Flow TPS
|   `-- denso_logistics_simulation_test.csv # Dữ liệu chuỗi thời gian 15 tháng (2026 - 2027)
`-- output/                               # Kết quả dự báo và mô phỏng tập kiểm thử năm 2027
    |-- table_1_workload_inbound.csv      # Dự báo nhu cầu Workload tại Dock Inbound
    |-- table_2_workload_outbound.csv     # Dự báo nhu cầu Workload tại Dock Outbound
    |-- table_3_storage_inbound.csv       # Mô phỏng tồn kho và phát hiện nghẽn sàn Inbound
    |-- table_4_storage_buffer.csv        # Mô phỏng tồn kho và phát hiện nghẽn kho đệm Buffer
    `-- table_5_storage_outbound.csv      # Mô phỏng tồn kho và phát hiện nghẽn sàn Outbound
```

---

## 2. Phần 1: Dữ Liệu Đầu Vào (Input Data)

### 2.1. Tổng quan tập dữ liệu gốc
- File dữ liệu: `data/input/denso_logistics_simulation_test.csv`
- Script khởi tạo: `data/input/data_generator.py`
- Khung thời gian: Từ 2026-01-01 00:00 đến 2027-03-31 23:00 (15 tháng liên tục)
- Tần suất quan sát: Từng giờ (Hourly, `freq='h'`)
- Tổng số quan sát: 10.920 dòng
- Phân chia tập dữ liệu:
  - Tập huấn luyện (Train): Toàn bộ năm 2026 (8.760 dòng) - dùng huấn luyện mô hình học máy.
  - Tập kiểm thử (Test / Control Room): Từ 2027-01-01 đến 2027-03-31 (2.160 dòng) - dùng kiểm thử mô hình và chạy Control Room.

### 2.2. Đặc tả các trường dữ liệu đầu vào (Input Schema)

| Tên Cột | Kiểu Dữ Liệu | Đơn Vị | Định Nghĩa & Ràng Buộc |
| :--- | :--- | :--- | :--- |
| `timestamp` | datetime | YYYY-MM-DD HH:MM | Mốc thời gian từng giờ vận hành. |
| `workload_inbound` | int | pallets | Khối lượng hàng cập cảng dỡ tại sàn Dock Inbound. |
| `workload_outbound` | int | pallets | Nhu cầu bốc hàng xuất xưởng tại sàn Dock Outbound. |
| `labor_inbound` | int | người | Số lượng nhân sự bố trí dỡ hàng tại khâu Inbound. |
| `labor_outbound` | int | người | Số lượng nhân sự bố trí bốc hàng tại khâu Outbound. |
| `amr_active` | int | xe | Số lượng xe tự hành AMR vận hành chuyển hàng (tối đa 8 xe). |
| `storage_inbound` | float | pallets | Lượng hàng thực tế tồn đọng tại sàn Inbound (Trần: 200). |
| `storage_buffer` | float | khay/thùng | Lượng hàng thực tế lưu tại kho đệm Kitting (Trần: 500). |
| `storage_outbound` | float | pallets | Lượng hàng thực tế tập kết tại sàn Outbound (Trần: 300). |
| `scenario` | string | text | Tên kịch bản vận hành (`Normal` hoặc các kịch bản kiểm thử biến động). |

### 2.3. Ràng buộc vật lý & Định mức vận hành
- Định mức năng lực:
  - Nhân công Inbound: 15.0 pallets/người/giờ (tỷ lệ dỡ tối đa 55%/giờ do kiểm hóa và scan mã).
  - Nhân công Outbound: 15.0 pallets/người/giờ.
  - Xe tự hành AMR: 14.0 pallets/xe/giờ (tối đa 8 xe vận hành).
- Cơ chế kiểm soát dòng chảy (TPS Pull Flow):
  - Áp lực ngược (Backpressure): Dừng đẩy hàng vào Buffer khi Buffer đầy (>= 500). Xe AMR dừng cấp hàng ra Outbound khi sàn Outbound đầy (>= 300).
  - Cân bằng tồn kho ERP: Tự động điều chỉnh nhu cầu Inbound bù đắp theo mức thâm hụt tồn kho mục tiêu (525 đơn vị).
- Kịch bản kiểm thử tích hợp (2027): Bao gồm 5 kịch bản biến động đột biến: `Volume Spike (+60%)`, `Zone Imbalance`, `Pre-Holiday Rush`, `Post-Holiday Recovery`, và `AMR Breakdown`.

---

## 3. Phần 2: Dữ Liệu Đầu Ra (Output Data)

Phần dữ liệu đầu ra gồm 5 bảng tổng hợp kết quả dự báo AI và mô phỏng chuỗi 3 tầng kho trên tập kiểm thử 2027 (2.160 giờ, từ 2027-01-01 00:00 đến 2027-03-31 23:00):

### 3.1. Dự báo Workload từng Dock (Bảng 1 & 2)

#### `data/output/table_1_workload_inbound.csv` (Dock Nhập Hàng Inbound)
- Mục đích: Đánh giá độ chính xác của mô hình AI khi dự báo khối lượng hàng nhập tại Dock Inbound và so sánh với năng lực dỡ hàng hiện có.
- Cấu trúc các cột:
  - `timestamp`: Mốc thời gian theo giờ trong năm 2027.
  - `actual_workload_inbound` (int): Nhu cầu hàng nhập thực tế tại Dock.
  - `pred_workload_inbound` (float): Nhu cầu hàng nhập dự báo bởi mô hình `HistGradientBoostingRegressor` (tích hợp Online Adaptive Bias).
  - `labor_inbound` (int): Số lượng nhân công được bố trí.
  - `capacity_inbound` (float): Năng lực xử lý thiết kế khả dụng (`labor_inbound * 15.0`).
  - `scenario` (string): Kịch bản vận hành tương ứng.

#### `data/output/table_2_workload_outbound.csv` (Dock Xuất Hàng Outbound)
- Mục đích: Đánh giá độ chính xác dự báo khối lượng hàng xuất tại Dock Outbound và đối chiếu với năng lực bốc xếp thực tế.
- Cấu trúc các cột:
  - `timestamp`: Mốc thời gian theo giờ trong năm 2027.
  - `actual_workload_outbound` (int): Nhu cầu hàng xuất thực tế tại Dock.
  - `pred_workload_outbound` (float): Nhu cầu hàng xuất dự báo bởi mô hình AI.
  - `labor_outbound` (int): Số lượng nhân công xuất hàng.
  - `amr_active` (int): Số lượng xe tự hành AMR phối hợp vận chuyển.
  - `capacity_outbound` (float): Năng lực xuất hàng thiết kế khả dụng (`labor_outbound * 15.0`).
  - `scenario` (string): Kịch bản vận hành tương ứng.

### 3.2. Mô phỏng tồn kho & Phát hiện điểm nghẽn 3 tầng (Bảng 3, 4, 5)

#### `data/output/table_3_storage_inbound.csv` (Sàn Dỡ Hàng Inbound)
- Mục đích: Theo dõi mức tồn kho mô phỏng tại sàn Inbound và cảnh báo nguy cơ tắc nghẽn khi hàng dỡ chậm hơn tốc độ cập cảng.
- Cấu trúc các cột:
  - `timestamp`: Mốc thời gian từng giờ.
  - `storage_inbound_sim` (float): Tồn kho mô phỏng động học theo năng lực xử lý.
  - `storage_inbound_actual` (float): Tồn kho ghi nhận thực tế từ hệ thống kho.
  - `max_threshold` (int): Ngưỡng trần vật lý của sàn (200 pallets).
  - `is_bottleneck` (bool): Đánh dấu trạng thái nghẽn (`True` khi tồn kho mô phỏng vượt ngưỡng cảnh báo/nghẽn).
  - `scenario` (string): Kịch bản vận hành tương ứng.

#### `data/output/table_4_storage_buffer.csv` (Kho Đệm Kitting Buffer)
- Mục đích: Giám sát lượng tích lũy tại kho đệm Kitting giữa khâu dỡ hàng và khâu vận chuyển xe AMR.
- Cấu trúc các cột:
  - `timestamp`: Mốc thời gian từng giờ.
  - `storage_buffer_sim` (float): Mức tồn kho mô phỏng tại Buffer (khay/thùng).
  - `storage_buffer_actual` (float): Mức tồn kho ghi nhận thực tế tại Buffer.
  - `max_threshold` (int): Ngưỡng trần vật lý của kho đệm (500 khay/thùng).
  - `is_bottleneck` (bool): Đánh dấu trạng thái nghẽn kho đệm.
  - `scenario` (string): Kịch bản vận hành tương ứng.

#### `data/output/table_5_storage_outbound.csv` (Sàn Xuất Hàng Outbound)
- Mục đích: Theo dõi lượng hàng tích tụ chờ xe tải lấy tại sàn Outbound, tránh quá tải diện tích sàn tập kết.
- Cấu trúc các cột:
  - `timestamp`: Mốc thời gian từng giờ.
  - `storage_outbound_sim` (float): Mức tồn kho mô phỏng tại sàn xuất (pallets).
  - `storage_outbound_actual` (float): Mức tồn kho ghi nhận thực tế tại sàn xuất.
  - `max_threshold` (int): Ngưỡng trần vật lý của sàn (300 pallets).
  - `is_bottleneck` (bool): Đánh dấu trạng thái nghẽn sàn tập kết xuất hàng.
  - `scenario` (string): Kịch bản vận hành tương ứng.
