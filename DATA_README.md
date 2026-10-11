# Dữ Liệu Mô Phỏng Logistics DENSO

Tài liệu này mô tả cấu trúc, phương pháp sinh và đặc tả kỹ thuật của tập dữ liệu `data/denso_logistics_simulation_test.csv` cùng script tạo dữ liệu `data/data_generator.py`.

---

## 1. Thông Tin Tổng Quan

- Tên file dữ liệu: `data/denso_logistics_simulation_test.csv`
- Script sinh dữ liệu: `data/data_generator.py`

- Khung thời gian: Từ 2026-01-01 00:00 đến 2027-03-31 23:00 (15 tháng liên tục)
- Tần suất: Theo từng giờ (Hourly, `freq='h'`)
- Quy mô: 10.944 dòng dữ liệu
- Phân chia tập dữ liệu:
  - Tập huấn luyện (Train): Toàn bộ năm 2026 (8.760 dòng)
  - Tập kiểm thử và vận hành (Test/Control Room): Từ 2027-01-01 đến 2027-03-31 (2.184 dòng)

---

## 2. Đặc Tả Cấu Trúc Bảng Dữ Liệu (Data Schema)

| Tên Cột | Kiểu Dữ Liệu | Đơn Vị | Mô Tả |
| :--- | :--- | :--- | :--- |
| `timestamp` | datetime | YYYY-MM-DD HH:MM | Mốc thời gian từng giờ vận hành. |
| `workload_inbound` | int | pallets | Khối lượng hàng cập cảng dỡ tại sàn Inbound. |
| `workload_outbound` | int | pallets | Nhu cầu bốc hàng xuất xưởng tại sàn Outbound. |
| `labor_inbound` | int | người | Số lượng công nhân được bố trí tại khâu Inbound. |
| `labor_outbound` | int | người | Số lượng công nhân được bố trí tại khâu Outbound. |
| `amr_active` | int | xe | Số lượng xe tự hành AMR hoạt động chở hàng (tối đa 8 xe). |
| `storage_inbound` | float | pallets | Lượng hàng thực tế tồn đọng tại sàn dỡ hàng Inbound. |
| `storage_buffer` | float | khay/thùng | Lượng hàng thực tế lưu trữ tại kho đệm Kitting Buffer. |
| `storage_outbound` | float | pallets | Lượng hàng thực tế tập kết tại sàn xuất xưởng Outbound. |
| `scenario` | string | text | Tên kịch bản vận hành (`Normal` hoặc các kịch bản kiểm thử). |

---

## 3. Định Mức Vật Lý Và Động Lực Học Dòng Chảy Kho

Dữ liệu được mô phỏng theo nguyên lý Kéo (Pull Flow) của Hệ thống Sản xuất Toyota (TPS) với các ràng buộc vật lý:

### Định mức sức chứa và năng lực
- Sàn Inbound: Trần 200 pallets. Định mức dỡ: 15.0 pallets/người/giờ. Tỷ lệ dỡ tối đa 55%/giờ do thời gian kiểm hóa và thủ tục quét mã.
- Kho đệm Kitting Buffer: Trần 500 khay/thùng. Năng lực xe tự hành AMR: 14.0 pallets/xe/giờ (tối đa 8 xe).
- Sàn Outbound: Trần 300 pallets. Định mức bốc xe: 15.0 pallets/người/giờ.

### Quy tắc kiểm soát dòng chảy
- Áp lực ngược (Backpressure): Không đẩy hàng vào Buffer nếu Buffer đầy (>= 500). Xe AMR dừng chuyển hàng từ Buffer ra Outbound nếu sàn Outbound đầy (>= 300).
- Phản hồi tồn kho ERP: Nhu cầu đặt hàng đầu vào (`workload_inbound`) tự động bù đắp theo mức thâm hụt so với mức tồn kho mục tiêu (525 đơn vị).
- Giới hạn dồn ứ (Soft Cap): Hàng hóa bị từ chối nhập viện nếu vượt quá 2.5 lần sức chứa thiết kế.

---

## 4. Các Kịch Bản Kiểm Thử (Năm 2027)

Tập dữ liệu năm 2027 tích hợp 5 kịch bản biến động bất thường phục vụ đánh giá năng lực thích ứng của AI và hệ thống điều độ:

1. `Volume Spike (+60%)`: 05/01/2027 08:00 đến 07/01/2027 18:00. Nhu cầu tăng vọt đồng thời ở cả hai chiều Inbound và Outbound.
2. `Zone Imbalance (Dock Congestion)`: 18/01/2027 08:00 đến 20/01/2027 18:00. Inbound tăng 70% trong khi Outbound giảm 40%, gây mất cân đối nhân lực.
3. `Pre-Holiday Rush`: 01/02/2027 06:00 đến 04/02/2027 22:00. Cao điểm xuất nhập trước Tết Nguyên Đán (Inbound +45%, Outbound +55%).
4. `Post-Holiday Recovery`: 15/02/2027 00:00 đến 17/02/2027 23:00. Khối lượng hàng tồn tích lũy phục hồi đồng loạt sau kỳ nghỉ.
5. `AMR Breakdown`: 10/03/2027 08:00 đến 11/03/2027 20:00. Hỏng hóc đội xe tự hành, chỉ còn 2/8 xe hoạt động, gây ứ nghẽn kho đệm.

---

## 5. Hướng Dẫn Tái Tạo Dữ Liệu

Thực thi lệnh sau tại thư mục gốc để sinh lại file dữ liệu:

```bash
python data/data_generator.py
```

