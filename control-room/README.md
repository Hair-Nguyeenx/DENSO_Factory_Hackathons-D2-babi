# Control Room - Trung Tâm Điều Hành Logistics

Module `control-room` cung cấp giao diện giám sát và điều độ vận hành thời gian thực cho hệ thống kho 3 tầng DENSO, được xây dựng trên nền tảng Streamlit.

---

## 1. Tổng Quan

Control Room phục vụ quản đốc và chuyên viên điều độ với các chức năng chính:
- Giám sát trạng thái dòng chảy kho và sức chứa sàn theo thời gian thực.
- Hiển thị kết quả dự báo nhu cầu từ mô hình AI theo các khung thời gian 1h, 3h và 12h.
- Phát hiện sớm điểm nghẽn khi mức tồn kho chạm ngưỡng cảnh báo 80% hoặc vượt trần thiết kế.
- Đề xuất kịch bản điều phối tự động (san tải Heijunka, điều chuyển nhân sự, tăng ca OT, bổ sung xe AMR).
- Cung cấp giao diện xem trước (Preview Modal) đối chiếu Before vs After và áp dụng trực tiếp phương án vào vận hành.

---

## 2. Cấu Trúc File

| Tên File | Chức Năng |
| :--- | :--- |
| `operation_dashboard.py` | Ứng dụng Streamlit chính của Control Room, tích hợp giao diện điều hành, biểu đồ, bảng phân tích và bộ nhớ phiên làm việc. |
| `README.md` | Tài liệu kỹ thuật của module. |

---

## 3. Kiến Trúc Điều Hành Khép Kín (Closed-Loop Rolling Control)

Hệ thống hoạt động theo vòng lặp kiểm soát trượt:
1. Tiếp nhận mốc thời gian hiện tại $t$ và khung dự báo $H$ (1h, 3h, 12h).
2. Lấy 5 giờ lịch sử thực tế và dự báo nhu cầu tương lai $t+1 \dots t+H$ từ `WarehouseForecaster`.
3. Kế thừa kế hoạch đã duyệt trong `master_schedule` (nếu có).
4. Chạy mô phỏng dòng chảy kho qua `CapacityModelEngine.simulate_24h`.
5. Quét nguy cơ vượt ngưỡng cảnh báo bằng `CapacityModelEngine.scan_bottlenecks`.
6. Nếu phát hiện điểm nghẽn, tự động kích hoạt bộ giải `CapacityModelEngine.solve_capacity_bottleneck`.
7. Hiển thị giải pháp trên giao diện; người dùng mở cửa sổ Preview để đánh giá và bấm duyệt để cập nhật vào `master_schedule`.

---

## 4. Các Thành Phần Giao Diện

### Sidebar (Thanh điều khiển)
- Tùy chọn giao diện: Chuyển đổi giữa Dark Mode và Light Mode.
- Khung thời gian dự báo: 1h, 3h, 12h.
- Chọn thời gian vận hành: Bộ chọn ngày và thanh trượt giờ trong tập kiểm thử 2027.
- Điều khiển bước thời gian: Nút tua +1 giờ (kế thừa tồn kho thực tế) và nút Làm mới (Reset).

### Hàng 1: Chỉ Số Trọng Yếu (KPIs)
- Workload Inbound (pallets/h)
- Workload Outbound (pallets/h)
- Tồn kho Sàn Inbound (pallets / 200, hiển thị % sức chứa)
- Tồn kho Kitting Buffer (khay / 500, hiển thị % sức chứa)
- Tồn kho Sàn Outbound (pallets / 300, hiển thị % sức chứa)

### Hàng 2: Dự Báo Nhu Cầu & Kế Hoạch Điều Độ
- Bảng 1 (Inbound) và Bảng 2 (Outbound): Thể hiện mốc giờ, dự báo AI, kế hoạch dỡ/xuất sau san tải, số lượng nhân công, số xe AMR, năng lực thiết kế và tỷ lệ tải/năng lực (%).
- Biểu đồ chuỗi thời gian: Thể hiện chuỗi thực tế 5 giờ trước, đường dự báo AI và đường kế hoạch điều độ.

### Hàng 3: Mô Phỏng Tồn Kho 3 Tầng
- Bảng 3 (Sàn Inbound), Bảng 4 (Kitting Buffer), Bảng 5 (Sàn Outbound): Thể hiện mức tồn kho mô phỏng từng giờ, đối chiếu với ngưỡng cảnh báo 80% và trần sức chứa.
- Phân loại trạng thái tự động: An toàn, Cảnh báo, Quá tải.

### Hàng 4: Phân Tích Điểm Nghẽn & Đề Xuất Điều Độ
- Bảng thống kê các mốc giờ có nguy cơ nghẽn, khu vực và mức độ vượt ngưỡng.
- Thông tin giải pháp đề xuất: Trạng thái, cấp độ can thiệp, chi phí nhân công (man-hours), danh sách các bước hành động cụ thể với số lượng pallet nguyên.
- Nút Mở chế độ Preview: Mở modal xem trước phương án điều phối.

### Cửa Sổ Xem Trước (Preview Modal)
- Thẻ so sánh đỉnh tồn kho Before vs After cho cả 3 tầng kho.
- 3 biểu đồ trực quan so sánh đường tồn kho trước can thiệp (nét đứt) và sau can thiệp (nét liền).
- Bảng phân tích chi tiết từng giờ với cột ghi chú cải thiện (ví dụ: Giảm tồn In, Tăng tồn Buffer).
- Nút Chấp nhận (Áp dụng phương án đề xuất) và nút Từ chối.

---

## 5. Quản Lý Trạng Thái Phiên (Session State)

Dashboard sử dụng các biến trạng thái bền vững để duy trì tính nhất quán khi Streamlit tự động tải lại:
- `master_schedule`: Lưu trữ thông số vận hành đã được duyệt theo từng mốc thời gian.
- `executed_history`: Lưu vết dữ liệu thực tế của các giờ đã hoàn thành.
- `committed_heijunka_in` / `committed_heijunka_out`: Ghi nhận lượng pallet đã dịch chuyển do điều độ để mô hình AI bóc tách sai số tự nhiên, tránh hiện tượng thiên lệch phản hồi (Feedback Confounding).
- `simulated_stocks`: Lưu trữ tồn kho cuối giờ $t$ làm đầu vào khởi điểm cho giờ $t+1$.

---

## 6. Hướng Dẫn Khởi Chạy

Khởi chạy ứng dụng từ thư mục gốc:

```bash
streamlit run control-room/operation_dashboard.py
```
