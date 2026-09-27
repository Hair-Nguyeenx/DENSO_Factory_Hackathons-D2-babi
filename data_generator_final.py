import pandas as pd
import numpy as np

# ==============================================================================
# 1. CẤU HÌNH HẰNG SỐ VẬT LÝ & ĐỊNH MỨC NĂNG LỰC
# ==============================================================================
MAX_STORAGE_INBOUND = 200    # Trần sức chứa sàn dỡ hàng (pallets)
MAX_STORAGE_BUFFER = 500     # Trần sức chứa kho đệm Kitting (khay/thùng)
MAX_STORAGE_OUTBOUND = 300   # Trần sức chứa sàn tập kết xuất xưởng (pallets)
MAX_AMR = 8                  # Tổng quy mô đội xe tự hành AMR trong kho

RATE_LABOR_IN = 15.0   # pallets / người / giờ
RATE_LABOR_OUT = 15.0  # pallets / người / giờ 
RATE_AMR = 14.0        # pallets / xe / giờ (AMR chở hàng từ buffer ra outbound)

# Trọng số mùa vụ 12 tháng
MONTH_FACTORS = {
    1: 1.2, 2: 0.90, 3: 0.85, 4: 0.95, 5: 1.00, 6: 1.00,
    7: 0.95, 8: 0.80, 9: 1.00, 10: 1.10, 11: 1.15, 12: 1.3
}

HOLIDAYS = {
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20", 
    "2026-04-30", "2026-05-01", "2026-09-02",
    "2027-01-01", "2027-02-05", "2027-02-06", "2027-02-07", "2027-02-08", "2027-02-09" 
}
PRE_HOLIDAYS = set((pd.to_datetime(list(HOLIDAYS)) - pd.Timedelta(days=1)).strftime('%Y-%m-%d')) - HOLIDAYS

def get_shift_baseline(dt):
    hour = dt.hour
    month = dt.month
    date_str = dt.strftime('%Y-%m-%d')
    day_of_week = dt.dayofweek
    
    # 1. Nhịp sinh học trong ngày (Diurnal)
    if 11 <= hour <= 12:  # Nghỉ trưa
        base_w_in, base_w_out = 20, 25
        l_in_base, l_out_base, amr_base = 3, 3, 4
    elif hour >= 20 or hour <= 5:  # Ca đêm
        base_w_in, base_w_out = 15, 20
        if 4 <= hour <= 5: base_w_out = 35
        l_in_base, l_out_base, amr_base = 2, 2, 3
    elif hour == 6 or hour == 7:  # Đầu ca sáng
        base_w_in, base_w_out = 50, 60
        l_in_base, l_out_base, amr_base = 4, 5, 6
    elif (8 <= hour <= 10) or (14 <= hour <= 16):  # Giờ cao điểm
        base_w_in, base_w_out = 90, 115
        l_in_base, l_out_base, amr_base = 7, 8, MAX_AMR
    else:  # Ca ngày bình thường
        base_w_in, base_w_out = 55, 70
        l_in_base, l_out_base, amr_base = 5, 6, 6

    # 2. Ngày lễ / Cuối tuần
    if date_str in HOLIDAYS:
        return 12, 15, 2, 2, 2
        
    mult = MONTH_FACTORS.get(month, 1.0)
    
    if day_of_week == 5:  # Thứ 7
        mult *= 0.8
        l_in_base = max(3, int(l_in_base * 0.8))
        l_out_base = max(3, int(l_out_base * 0.8))
        amr_base = max(4, int(amr_base * 0.8))
    elif day_of_week == 6:  # Chủ nhật
        mult *= 0.5
        l_in_base = max(2, int(l_in_base * 0.5))
        l_out_base = max(2, int(l_out_base * 0.5))
        amr_base = max(3, int(amr_base * 0.5))

    if date_str in PRE_HOLIDAYS:
        mult *= 1.35
        
    return base_w_in * mult, base_w_out * mult, l_in_base, l_out_base, amr_base

def main():
    np.random.seed(42)
    print("Khởi chạy Engine mô phỏng Logistics DENSO (Pull Flow Version)...")
    
    timestamps = pd.date_range(start="2026-01-01 00:00", end="2027-03-31 23:00", freq="h")
    
    # Khởi tạo tồn kho ban đầu quanh mức 40-70% định mức
    s_in = int(MAX_STORAGE_INBOUND * 0.4)
    s_buf = int(MAX_STORAGE_BUFFER * 0.65)
    s_out = int(MAX_STORAGE_OUTBOUND * 0.4)
    
    w_in_prev, w_out_prev = 50.0, 60.0
    
    records = []

    for dt in timestamps:
        hour = dt.hour
        dt_str = dt.strftime('%Y-%m-%d %H:%M')
        
        base_w_in, base_w_out, l_in_base, l_out_base, amr_base = get_shift_baseline(dt)
        scenario = 'Normal'

        # --- DAO ĐỘNG TÀI NGUYÊN (JITTER) ---
        min_labor = 2 if (20 <= hour or hour <= 5) else 3
        min_amr = 3 if (20 <= hour or hour <= 5) else 4
        
        l_in = max(min_labor, l_in_base + np.random.choice([-1, 0, 0, 1]))
        l_out = max(min_labor, l_out_base + np.random.choice([-1, 0, 0, 1]))
        amr = min(MAX_AMR, max(min_amr, amr_base + np.random.choice([-1, 0, 0, 1])))

        # --- 5 KỊCH BẢN BẤT THƯỜNG (CHỈ TẬP TEST 2027) ---
        if '2027-01-05 08:00' <= dt_str <= '2027-01-07 18:00':
            base_w_in *= 1.6
            base_w_out *= 1.6
            scenario = 'Volume Spike (+60%)'  
        elif '2027-01-18 08:00' <= dt_str <= '2027-01-20 18:00':
            base_w_in *= 1.7
            base_w_out *= 0.6
            scenario = 'Zone Imbalance (Dock Congestion)'
        elif '2027-02-01 06:00' <= dt_str <= '2027-02-04 22:00':
            base_w_in *= 1.45
            base_w_out *= 1.55
            scenario = 'Pre-Holiday Rush'
        elif '2027-02-15 00:00' <= dt_str <= '2027-02-17 23:00':
            base_w_in *= 1.6
            base_w_out *= 1.6
            scenario = 'Post-Holiday Recovery'
        elif '2027-03-10 08:00' <= dt_str <= '2027-03-11 20:00':
            amr = 2  # Ép cứng hỏng xe, mất năng lực kéo
            scenario = 'AMR Breakdown'

        # ==============================================================
        # SINH DEMAND VỚI ERP FEEDBACK (Điều tiết Inbound theo tổng tồn kho)
        # ==============================================================
        w_in_raw = 0.6 * w_in_prev + 0.4 * base_w_in + np.random.normal(0, 4)
        w_out_raw = 0.6 * w_out_prev + 0.4 * base_w_out + np.random.normal(0, 5)
        
        # ERP điều chỉnh đặt hàng (w_in) bù đắp thâm hụt so với Target Inventory
        target_total_inv = MAX_STORAGE_INBOUND * 0.4 + MAX_STORAGE_BUFFER * 0.65 + MAX_STORAGE_OUTBOUND * 0.4
        inv_deficit = target_total_inv - (s_in + s_buf + s_out)
        w_in = max(0, int(w_in_raw + inv_deficit * 0.15))
        w_out = max(0, int(w_out_raw))

        # ==============================================================
        # ĐỘNG LỰC HỌC CHUỖI CUNG ỨNG (DISCRETE EVENT PULL FLOW)
        # ==============================================================
        # Giới hạn dồn ứ (Soft Cap) - Hàng hóa bị từ chối nhập viện nếu vượt 2.5 lần Max
        SOFT_CAP_IN = MAX_STORAGE_INBOUND * 2.5
        SOFT_CAP_BUF = MAX_STORAGE_BUFFER * 2.5
        SOFT_CAP_OUT = MAX_STORAGE_OUTBOUND * 2.5
        
        # 1. Khâu Inbound Dock
        cap_in = l_in * RATE_LABOR_IN
        available_in = s_in + w_in
        # Áp lực ngược (Backpressure): Không đẩy vào Buffer nếu Buffer chạm ngưỡng định mức thiết kế MAX
        space_in_buf = max(0, MAX_STORAGE_BUFFER - s_buf)
        # Chỉ dỡ được tối đa 55% hàng có trên dock mỗi giờ do thời gian chờ kiểm hóa
        flow_in = int(min(available_in * 0.55, cap_in, space_in_buf)) 
        
        # 2. Khâu Kitting Buffer & AMR Pull
        cap_amr = amr * RATE_AMR
        # NGUYÊN LÝ PULL: AMR kéo hàng từ Buffer bù vào Outbound
        target_out = MAX_STORAGE_OUTBOUND * 0.5
        if 20 <= hour or hour <= 5: target_out = MAX_STORAGE_OUTBOUND * 0.8  # Đêm dồn hàng
        elif hour == 6 or hour == 7: target_out = MAX_STORAGE_OUTBOUND * 0.3 # Sáng xả mạnh
        
        amr_demand = max(0, w_out + (target_out - s_out) * 0.5)
        available_buf = s_buf + flow_in
        # Áp lực ngược: AMR không chở ra nếu sàn Outbound đã chạm ngưỡng định mức thiết kế MAX
        space_in_out = max(0, MAX_STORAGE_OUTBOUND - s_out)
        flow_out = int(min(available_buf * 0.7, cap_amr, amr_demand, space_in_out))
        
        # 3. Khâu Sàn xuất Outbound & Xe tải nhận hàng
        cap_out = l_out * RATE_LABOR_OUT
        truck_demand = w_out
        available_out = s_out + flow_out
        ship_out = int(min(available_out, cap_out, truck_demand))
        
        # 4. Cập nhật tồn kho (BẢO TOÀN DÒNG CHẢY 100%)
        s_in = available_in - flow_in
        s_buf = available_buf - flow_out
        s_out = available_out - ship_out
        
        # 5. Cắt ngọn vượt giới hạn tuyệt đối (Soft Cap)
        s_in = min(s_in, SOFT_CAP_IN)
        s_buf = min(s_buf, SOFT_CAP_BUF)
        s_out = min(s_out, SOFT_CAP_OUT)

        records.append({
            'timestamp': dt_str,
            'workload_inbound': w_in,
            'workload_outbound': w_out,
            'labor_inbound': l_in,
            'labor_outbound': l_out,
            'amr_active': amr,
            'storage_inbound': s_in,
            'storage_buffer': s_buf,
            'storage_outbound': s_out,
            'scenario': scenario
        })
        
        w_in_prev, w_out_prev = w_in, w_out

    df = pd.DataFrame(records)
    output_filename = "denso_logistics_simulation_test.csv"
    df.to_csv(output_filename, index=False)
    print(f"Hoàn thành! Đã tạo thành công {len(df)} dòng dữ liệu.")

if __name__ == "__main__":
    main()
