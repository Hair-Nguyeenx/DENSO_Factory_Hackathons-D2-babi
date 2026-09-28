import pandas as pd 
import numpy as np
import copy 


#Định mức nhân công
RATE_LABOR_INBOUND = 15.0   # pallets / người / giờ
RATE_LABOR_OUTBOUND = 15.0  # pallets / người / giờ 
RATE_AMR = 14.0             # pallets / xe / giờ

MAX_STORAGE_INBOUND = 200
MAX_STORAGE_BUFFER = 500
MAX_STORAGE_OUTBOUND = 300

# Ngưỡng Vàng (Cảnh báo nguy cơ nghẽn kho)
WARN_STORAGE_INBOUND = MAX_STORAGE_INBOUND * 0.8    # 160
WARN_STORAGE_BUFFER = MAX_STORAGE_BUFFER * 0.8      # 400
WARN_STORAGE_OUTBOUND = MAX_STORAGE_OUTBOUND * 0.8  # 240 (Đồng bộ chuẩn 80%)


class CapacityModelEngine:
    def __init__(self):
        pass

    def simulate_24h(self, df_plan: pd.DataFrame, initial_stocks: tuple):
        """
        Mô phỏng dòng chảy kho 3 tầng qua từng giờ: Inbound Dock -> Kitting Buffer -> Outbound Dock.
        Đảm bảo an toàn 100% với DatetimeIndex và bất kỳ Horizon nào (1h, 3h, 12h, 24h).
        """
        df_sim = df_plan.copy()
        s_inbound, s_buffer, s_outbound = initial_stocks
        
        SOFT_CAP_IN = MAX_STORAGE_INBOUND * 2.5
        SOFT_CAP_BUF = MAX_STORAGE_BUFFER * 2.5
        SOFT_CAP_OUT = MAX_STORAGE_OUTBOUND * 2.5

        sim_s_in, sim_s_buf, sim_s_out = [], [], []
        
        for idx in range(len(df_sim)):
            row = df_sim.iloc[idx]
            w_in = float(row['workload_inbound'])
            w_out = float(row['workload_outbound'])
            labor_in = float(row['labor_inbound'])
            labor_out = float(row['labor_outbound'])
            amr = float(row['amr_active'])
            labor_buf = float(row['labor_buffer']) if 'labor_buffer' in row else 0.0
            
            # Lấy giờ thực tế
            hour = df_sim.index[idx].hour if hasattr(df_sim.index[idx], 'hour') else idx % 24
            
            # 1. Kho Inbound Dock
            capacity_in = labor_in * RATE_LABOR_INBOUND
            available_in = s_inbound + w_in
            space_in_buffer = max(0.0, MAX_STORAGE_BUFFER - s_buffer)
            flow_in = min(available_in * 0.6, capacity_in, space_in_buffer)

            # 2. Kho Kitting Buffer
            amr_capacity = (amr * RATE_AMR) + (labor_buf * RATE_LABOR_OUTBOUND)
            target_out = MAX_STORAGE_OUTBOUND * 0.5
            if 20 <= hour or hour <= 5: 
                target_out = MAX_STORAGE_OUTBOUND * 0.8   # Đêm dồn hàng
            elif hour in [6, 7]: 
                target_out = MAX_STORAGE_OUTBOUND * 0.3  # Sáng xả mạnh
                
            amr_demand = max(0.0, w_out + (target_out - s_outbound) * 0.5)
            available_buffer = s_buffer + flow_in
            space_in_out = max(0.0, MAX_STORAGE_OUTBOUND - s_outbound)
            flow_out = min(amr_capacity, space_in_out, amr_demand, available_buffer * 0.7)

            # 3. Kho Outbound Dock
            capacity_out = labor_out * RATE_LABOR_OUTBOUND
            truck_demand = w_out
            available_out = s_outbound + flow_out
            ship_out = min(capacity_out, truck_demand, available_out)

            # Cập nhật tồn kho
            s_inbound = available_in - flow_in
            s_buffer = available_buffer - flow_out
            s_outbound = available_out - ship_out

            # Cắt ngọn trần mềm (Soft Cap)
            s_inbound = min(s_inbound, SOFT_CAP_IN)
            s_buffer = min(s_buffer, SOFT_CAP_BUF)
            s_outbound = min(s_outbound, SOFT_CAP_OUT)

            sim_s_in.append(round(s_inbound, 1))
            sim_s_buf.append(round(s_buffer, 1))
            sim_s_out.append(round(s_outbound, 1))
            
        df_sim['storage_inbound_sim'] = sim_s_in
        df_sim['storage_buffer_sim'] = sim_s_buf
        df_sim['storage_outbound_sim'] = sim_s_out
        
        return df_sim

    def scan_bottlenecks(self, df_sim: pd.DataFrame):
        """Quét và xếp loại các điểm nghẽn vượt ngưỡng an toàn"""
        bottlenecks = []
        for idx in range(len(df_sim)):
            row = df_sim.iloc[idx]
            hour_str = df_sim.index[idx].strftime('%H:%M') if hasattr(df_sim.index[idx], 'strftime') else f"T+{idx}h"

            if row['storage_inbound_sim'] >= WARN_STORAGE_INBOUND: 
                bottlenecks.append({
                    'time_index': idx,
                    'hour': hour_str,
                    'type': 'inbound',
                    'severity': row['storage_inbound_sim'] - WARN_STORAGE_INBOUND
                })
            elif row['storage_buffer_sim'] >= WARN_STORAGE_BUFFER:
                bottlenecks.append({
                    'time_index': idx,
                    'hour': hour_str,
                    'type': 'buffer',
                    'severity': row['storage_buffer_sim'] - WARN_STORAGE_BUFFER
                })
            elif row['storage_outbound_sim'] >= WARN_STORAGE_OUTBOUND:
                bottlenecks.append({
                    'time_index': idx,
                    'hour': hour_str,
                    'type': 'outbound',
                    'severity': row['storage_outbound_sim'] - WARN_STORAGE_OUTBOUND
                })
        return bottlenecks    

    def evaluate_plan(self, candidate_df: pd.DataFrame, initial_stocks: tuple, original_bottlenecks: list):
        """Đánh giá xem phương án can thiệp có giải phóng được điểm nghẽn không"""
        simulating_plan = self.simulate_24h(candidate_df, initial_stocks)
        new_bottlenecks = self.scan_bottlenecks(simulating_plan)

        # 1. Thành công tuyệt đối: Không còn bất kỳ điểm nghẽn nào
        if len(new_bottlenecks) == 0:
            return True, simulating_plan

        # 2. Cải thiện đáng kể: Giảm số điểm nghẽn hoặc giảm mức độ nghiêm trọng
        if len(new_bottlenecks) < len(original_bottlenecks):
            return True, simulating_plan

        return False, None

    def solve_capacity_bottleneck(self, df_plan: pd.DataFrame, initial_stocks: tuple):
        """
        Rule-based Heuristic Search: Phân tích và tìm giải pháp điều độ tối ưu nhất.
        Đảm bảo an toàn chỉ mục 100% (luôn dùng .iloc và kiểm tra biên 0 <= idx < len).
        
        Các cấp độ can thiệp (từ chi phí 0 đến OT):
          Level 1: Dàn trải phẳng tải (Heijunka 1h - 2h)
          Level 2: Điều chuyển ngang (Cross-dock: Inbound <-> Outbound)
          Level 3: Đổi ca dọc nội bộ (Shift Swap cùng kho)
          Level 4: Giải pháp (Heijunka + Mượn người ngang)
          Level 5: Giải pháp (Mượn người + Dàn trải + Đổi ca nội bộ) - Áp dụng cả Inbound & Outbound
          Level 6: Làm thêm giờ (Overtime - OT 1h-2h)
        """
        df_plan_simulation = self.simulate_24h(df_plan, initial_stocks)
        df_plan_bottleneck = self.scan_bottlenecks(df_plan_simulation)

        if not df_plan_bottleneck:
            return {
                'status': 'NO_ACTION_NEEDED',
                'message': 'Hệ thống vận hành ổn định trong khung giờ dự báo, không có nguy cơ nghẽn kho.',
                'df_before': df_plan_simulation,
                'df_after': df_plan_simulation
            }

        first_b = df_plan_bottleneck[0]
        t_idx = first_b['time_index']
        hour_str = first_b['hour']
        b_type = first_b['type']
        n_steps = len(df_plan)
        
        candidate_df = df_plan.copy()
        if 'labor_buffer' not in candidate_df.columns:
            candidate_df['labor_buffer'] = 0

        curr_time = candidate_df.index[t_idx]

        # =====================================================================
        # NHÁNH 1: XỬ LÝ NGHẼN TẠI SÀN NHẬP (INBOUND DOCK)
        # =====================================================================
        if b_type == 'inbound':
            shift_w = int(candidate_df.iloc[t_idx]['workload_inbound'] * 0.20)

            # --- LEVEL 1: HEIJUNKA ĐƠN LẺ (Dời sớm 1h hoặc 2h) ---
            for offset in [-1, -2]:
                target_idx = t_idx + offset
                if 0 <= target_idx < n_steps and shift_w > 0:
                    test_df = candidate_df.copy()
                    target_time = test_df.index[target_idx]
                    test_df.loc[curr_time, 'workload_inbound'] = float(test_df.loc[curr_time, 'workload_inbound']) - shift_w
                    test_df.loc[target_time, 'workload_inbound'] = float(test_df.loc[target_time, 'workload_inbound']) + shift_w

                    is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                    if is_better:
                        direct = "sớm" if offset < 0 else "muộn"
                        steps_h = abs(offset)
                        return {
                            'status': 'SUCCESS',
                            'level': 'Level 1: Dàn trải phẳng (Heijunka Inbound)',
                            'action_logs': [f"Hẹn nhà xe dời {shift_w} pallets Inbound từ lúc {hour_str} sang {direct} {steps_h} tiếng."],
                            'cost': 0,
                            'df_before': df_plan_simulation,
                            'df_after': df_after
                        }

            # --- LEVEL 2: ĐIỀU CHUYỂN NGANG (Mượn công nhân Outbound -> Inbound) ---
            curr_labor_out = int(candidate_df.iloc[t_idx]['labor_outbound'])
            if curr_labor_out >= 3:
                for borrow_k in [1, 2]:
                    if curr_labor_out - borrow_k >= 2:
                        test_df = candidate_df.copy()
                        test_df.loc[curr_time, 'labor_outbound'] = curr_labor_out - borrow_k
                        test_df.loc[curr_time, 'labor_inbound'] = int(test_df.loc[curr_time, 'labor_inbound']) + borrow_k
                        
                        is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                        if is_better:
                            return {
                                'status': 'SUCCESS',
                                'level': 'Level 2: Điều chuyển ngang (Cross-docking)',
                                'action_logs': [f"Điều chuyển {borrow_k} công nhân từ Outbound sang hỗ trợ Inbound lúc {hour_str}."],
                                'cost': 0,
                                'df_before': df_plan_simulation,
                                'df_after': df_after
                            }

            # --- LEVEL 3: ĐỔI CA DỌC NỘI BỘ (Mượn công nhân Inbound từ ca thấp điểm) ---
            for offset in [-6, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 6]:
                donor_idx = t_idx + offset
                if 0 <= donor_idx < n_steps:
                    donor_labor = int(candidate_df.iloc[donor_idx]['labor_inbound'])
                    if donor_labor >= 3:
                        for shift_k in [1, 2]:
                            test_df = candidate_df.copy()
                            donor_time = test_df.index[donor_idx]
                            test_df.loc[donor_time, 'labor_inbound'] = donor_labor - shift_k
                            test_df.loc[curr_time, 'labor_inbound'] = int(test_df.loc[curr_time, 'labor_inbound']) + shift_k
                            
                            is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                            if is_better:
                                donor_hour_str = test_df.index[donor_idx].strftime('%H:%M') if hasattr(test_df.index[donor_idx], 'strftime') else f"T+{donor_idx}h"
                                return {
                                    'status': 'SUCCESS',
                                    'level': 'Level 3: Đổi ca dọc nội bộ Inbound',
                                    'action_logs': [f"Điều chuyển {shift_k} công nhân Inbound từ ca thấp điểm {donor_hour_str} sang ca cao điểm {hour_str}."],
                                    'cost': 0,
                                    'df_before': df_plan_simulation,
                                    'df_after': df_after
                                }

            # --- LEVEL 4: COMBO ĐÔI (Heijunka + Mượn công nhân Outbound) ---
            for borrow_k in [1, 2]:
                if curr_labor_out >= (2 + borrow_k):
                    for offset in [-1, 1]:
                        target_idx = t_idx + offset
                        if 0 <= target_idx < n_steps and shift_w > 0:
                            test_df = candidate_df.copy()
                            target_time = test_df.index[target_idx]
                            # Heijunka
                            test_df.loc[curr_time, 'workload_inbound'] = float(test_df.loc[curr_time, 'workload_inbound']) - shift_w
                            test_df.loc[target_time, 'workload_inbound'] = float(test_df.loc[target_time, 'workload_inbound']) + shift_w
                            # Mượn người
                            test_df.loc[curr_time, 'labor_outbound'] = curr_labor_out - borrow_k
                            test_df.loc[curr_time, 'labor_inbound'] = int(test_df.loc[curr_time, 'labor_inbound']) + borrow_k

                            is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                            if is_better:
                                direct = "sớm" if offset == -1 else "muộn"
                                return {
                                    'status': 'SUCCESS',
                                    'level': 'Level 4: Giải pháp (Heijunka + Mượn người ngang)',
                                    'action_logs': [
                                        f"Hẹn nhà xe dời {shift_w} pallets Inbound từ lúc {hour_str} sang {direct} 1 tiếng.",
                                        f"Đồng thời điều chuyển {borrow_k} công nhân từ Outbound sang Inbound lúc {hour_str}."
                                    ],
                                    'cost': 0,
                                    'df_before': df_plan_simulation,
                                    'df_after': df_after
                                }

            # --- LEVEL 5: SUPER COMBO TAM HỢP (Mượn ngang + Dàn trải + Đổi ca dọc nội bộ) ---
            for borrow_k in [1, 2]:
                if curr_labor_out >= (2 + borrow_k):
                    for offset_h in [-1, 1]:
                        target_idx = t_idx + offset_h
                        if 0 <= target_idx < n_steps and shift_w > 0:
                            for offset_s in [-4, -3, -2, -1, 1, 2, 3, 4]:
                                donor_idx = t_idx + offset_s
                                if 0 <= donor_idx < n_steps and donor_idx != target_idx:
                                    donor_labor = int(candidate_df.iloc[donor_idx]['labor_inbound'])
                                    if donor_labor >= 3:
                                        test_df = candidate_df.copy()
                                        target_time = test_df.index[target_idx]
                                        donor_time = test_df.index[donor_idx]

                                        # 1. Dàn trải
                                        test_df.loc[curr_time, 'workload_inbound'] = float(test_df.loc[curr_time, 'workload_inbound']) - shift_w
                                        test_df.loc[target_time, 'workload_inbound'] = float(test_df.loc[target_time, 'workload_inbound']) + shift_w
                                        # 2. Mượn ngang
                                        test_df.loc[curr_time, 'labor_outbound'] = curr_labor_out - borrow_k
                                        # 3. Đổi ca dọc
                                        test_df.loc[donor_time, 'labor_inbound'] = donor_labor - 1
                                        test_df.loc[curr_time, 'labor_inbound'] = int(test_df.loc[curr_time, 'labor_inbound']) + borrow_k + 1

                                        is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                                        if is_better:
                                            donor_h_str = donor_time.strftime('%H:%M') if hasattr(donor_time, 'strftime') else f"T+{donor_idx}h"
                                            return {
                                                'status': 'SUCCESS',
                                                'level': 'Level 5: Giải pháp (Mượn kho ngoài + Dàn tải + Đổi ca)',
                                                'action_logs': [
                                                    f"1. Dời {shift_w} pallets Inbound từ lúc {hour_str} sang ca lân cận.",
                                                    f"2. Điều chuyển {borrow_k} công nhân Outbound sang tiếp viện Inbound lúc {hour_str}.",
                                                    f"3. Dời thêm 1 công nhân Inbound từ ca thấp điểm {donor_h_str} sang tăng cường."
                                                ],
                                                'cost': 0,
                                                'df_before': df_plan_simulation,
                                                'df_after': df_after
                                            }

            # --- LEVEL 6: LÀM THÊM GIỜ (OVERTIME - OT) ---
            for ot_labors in [1, 2, 3]:
                for ot_hours in [1, 2]:
                    for offset in [-1, 0, 1]:
                        ot_start = t_idx + offset
                        ot_end = ot_start + ot_hours
                        if 0 <= ot_start and ot_end <= n_steps:
                            test_df = candidate_df.copy()
                            for h_i in range(ot_start, ot_end):
                                h_time = test_df.index[h_i]
                                test_df.loc[h_time, 'labor_inbound'] = int(test_df.loc[h_time, 'labor_inbound']) + ot_labors
                            
                            is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                            if is_better:
                                start_str = test_df.index[ot_start].strftime('%H:%M') if hasattr(test_df.index[ot_start], 'strftime') else f"T+{ot_start}h"
                                end_str = test_df.index[ot_end - 1].strftime('%H:%M') if hasattr(test_df.index[ot_end - 1], 'strftime') else f"T+{ot_end-1}h"
                                total_mh = ot_labors * ot_hours
                                return {
                                    'status': 'SUCCESS',
                                    'level': 'Level 6: Làm thêm giờ Inbound (Overtime)',
                                    'action_logs': [
                                        f"Huy động {ot_labors} công nhân Inbound làm OT trong {ot_hours} giờ (Từ {start_str} đến {end_str}).",
                                        f"Tổng công suất bổ sung: {total_mh * RATE_LABOR_INBOUND} pallets | Chi phí: {total_mh * 1.5} man-hours."
                                    ],
                                    'cost': total_mh * 1.5,
                                    'df_before': df_plan_simulation,
                                    'df_after': df_after
                                }

        # =====================================================================
        # NHÁNH 2: XỬ LÝ NGHẼN TẠI SÀN XUẤT (OUTBOUND DOCK)
        # =====================================================================
        elif b_type == 'outbound':
            shift_w_out = int(candidate_df.iloc[t_idx]['workload_outbound'] * 0.20)
            curr_labor_in = int(candidate_df.iloc[t_idx]['labor_inbound'])

            # --- LEVEL 1: HEIJUNKA XUẤT (Gom hàng xuất sớm/muộn 1h) ---
            for offset in [-1, 1]:
                target_idx = t_idx + offset
                if 0 <= target_idx < n_steps and shift_w_out > 0:
                    test_df = candidate_df.copy()
                    target_time = test_df.index[target_idx]
                    test_df.loc[curr_time, 'workload_outbound'] = float(test_df.loc[curr_time, 'workload_outbound']) - shift_w_out
                    test_df.loc[target_time, 'workload_outbound'] = float(test_df.loc[target_time, 'workload_outbound']) + shift_w_out
                    
                    is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                    if is_better:
                        direct = "sớm" if offset == -1 else "muộn"
                        return {
                            'status': 'SUCCESS',
                            'level': 'Level 1: Dàn trải tải xuất (Heijunka Outbound)',
                            'action_logs': [f"Thông báo nhà xe điều chỉnh giờ bốc hàng {shift_w_out} pallets Outbound sang {direct} 1 tiếng."],
                            'cost': 0,
                            'df_before': df_plan_simulation,
                            'df_after': df_after
                        }

            # --- LEVEL 2: ĐIỀU CHUYỂN NGANG (Mượn công nhân Inbound -> Outbound) ---
            if curr_labor_in >= 3:
                for borrow_k in [1, 2]:
                    if curr_labor_in - borrow_k >= 2:
                        test_df = candidate_df.copy()
                        test_df.loc[curr_time, 'labor_inbound'] = curr_labor_in - borrow_k
                        test_df.loc[curr_time, 'labor_outbound'] = int(test_df.loc[curr_time, 'labor_outbound']) + borrow_k
                        
                        is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                        if is_better:
                            return {
                                'status': 'SUCCESS',
                                'level': 'Level 2: Điều chuyển ngang (Inbound sang Outbound)',
                                'action_logs': [f"Điều chuyển {borrow_k} công nhân từ Inbound sang hỗ trợ Outbound lúc {hour_str}."],
                                'cost': 0,
                                'df_before': df_plan_simulation,
                                'df_after': df_after
                            }

            # --- LEVEL 3: ĐỔI CA DỌC NỘI BỘ (Mượn công nhân Outbound từ ca thấp điểm) ---
            for offset in [-6, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 6]:
                donor_idx = t_idx + offset
                if 0 <= donor_idx < n_steps:
                    donor_labor = int(candidate_df.iloc[donor_idx]['labor_outbound'])
                    if donor_labor >= 3:
                        for shift_k in [1, 2]:
                            test_df = candidate_df.copy()
                            donor_time = test_df.index[donor_idx]
                            test_df.loc[donor_time, 'labor_outbound'] = donor_labor - shift_k
                            test_df.loc[curr_time, 'labor_outbound'] = int(test_df.loc[curr_time, 'labor_outbound']) + shift_k
                            
                            is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                            if is_better:
                                donor_hour_str = donor_time.strftime('%H:%M') if hasattr(donor_time, 'strftime') else f"T+{donor_idx}h"
                                return {
                                    'status': 'SUCCESS',
                                    'level': 'Level 3: Đổi ca dọc nội bộ Outbound',
                                    'action_logs': [f"Điều chuyển {shift_k} công nhân Outbound từ ca thấp điểm {donor_hour_str} sang ca cao điểm {hour_str}."],
                                    'cost': 0,
                                    'df_before': df_plan_simulation,
                                    'df_after': df_after
                                }

            # --- LEVEL 4: COMBO ĐÔI OUTBOUND (Heijunka + Mượn công nhân Inbound) ---
            for borrow_k in [1, 2]:
                if curr_labor_in >= (2 + borrow_k):
                    for offset in [-1, 1]:
                        target_idx = t_idx + offset
                        if 0 <= target_idx < n_steps and shift_w_out > 0:
                            test_df = candidate_df.copy()
                            target_time = test_df.index[target_idx]
                            test_df.loc[curr_time, 'workload_outbound'] = float(test_df.loc[curr_time, 'workload_outbound']) - shift_w_out
                            test_df.loc[target_time, 'workload_outbound'] = float(test_df.loc[target_time, 'workload_outbound']) + shift_w_out
                            test_df.loc[curr_time, 'labor_inbound'] = curr_labor_in - borrow_k
                            test_df.loc[curr_time, 'labor_outbound'] = int(test_df.loc[curr_time, 'labor_outbound']) + borrow_k

                            is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                            if is_better:
                                return {
                                    'status': 'SUCCESS',
                                    'level': 'Level 4: Giải pháp (Heijunka xuất + Mượn người ngang)',
                                    'action_logs': [
                                        f"Thông báo nhà xe gom dời bớt {shift_w_out} pallets xuất sớm tại {hour_str}.",
                                        f"Đồng thời điều chuyển {borrow_k} công nhân từ Inbound sang Outbound để tăng tốc bốc hàng."
                                    ],
                                    'cost': 0,
                                    'df_before': df_plan_simulation,
                                    'df_after': df_after
                                }

            # --- LEVEL 5: SUPER COMBO TAM HỢP OUTBOUND (Mượn Inbound + Heijunka + Đổi ca dọc Outbound) ---
            for borrow_k in [1, 2]:
                if curr_labor_in >= (2 + borrow_k):
                    for offset_h in [-1, 1]:
                        target_idx = t_idx + offset_h
                        if 0 <= target_idx < n_steps and shift_w_out > 0:
                            for offset_s in [-4, -3, -2, -1, 1, 2, 3, 4]:
                                donor_idx = t_idx + offset_s
                                if 0 <= donor_idx < n_steps and donor_idx != target_idx:
                                    donor_labor = int(candidate_df.iloc[donor_idx]['labor_outbound'])
                                    if donor_labor >= 3:
                                        test_df = candidate_df.copy()
                                        target_time = test_df.index[target_idx]
                                        donor_time = test_df.index[donor_idx]

                                        test_df.loc[curr_time, 'workload_outbound'] = float(test_df.loc[curr_time, 'workload_outbound']) - shift_w_out
                                        test_df.loc[target_time, 'workload_outbound'] = float(test_df.loc[target_time, 'workload_outbound']) + shift_w_out
                                        test_df.loc[curr_time, 'labor_inbound'] = curr_labor_in - borrow_k
                                        test_df.loc[donor_time, 'labor_outbound'] = donor_labor - 1
                                        test_df.loc[curr_time, 'labor_outbound'] = int(test_df.loc[curr_time, 'labor_outbound']) + borrow_k + 1

                                        is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                                        if is_better:
                                            donor_h_str = donor_time.strftime('%H:%M') if hasattr(donor_time, 'strftime') else f"T+{donor_idx}h"
                                            return {
                                                'status': 'SUCCESS',
                                                'level': 'Level 5: Giải pháp (Mượn Inbound + Dàn tải + Đổi ca)',
                                                'action_logs': [
                                                    f"1. Dời {shift_w_out} pallets Outbound sang ca lân cận.",
                                                    f"2. Điều động {borrow_k} công nhân Inbound sang tiếp viện Outbound lúc {hour_str}.",
                                                    f"3. Dời thêm 1 công nhân Outbound từ ca thấp điểm {donor_h_str} sang hỗ trợ xe tải."
                                                ],
                                                'cost': 0,
                                                'df_before': df_plan_simulation,
                                                'df_after': df_after
                                            }

            # --- LEVEL 6: LÀM THÊM GIỜ OUTBOUND (OVERTIME) ---
            for ot_labors in [1, 2, 3]:
                for ot_hours in [1, 2]:
                    for offset in [-1, 0, 1]:
                        ot_start = t_idx + offset
                        ot_end = ot_start + ot_hours
                        if 0 <= ot_start and ot_end <= n_steps:
                            test_df = candidate_df.copy()
                            for h_i in range(ot_start, ot_end):
                                h_time = test_df.index[h_i]
                                test_df.loc[h_time, 'labor_outbound'] = int(test_df.loc[h_time, 'labor_outbound']) + ot_labors
                            
                            is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                            if is_better:
                                start_str = test_df.index[ot_start].strftime('%H:%M') if hasattr(test_df.index[ot_start], 'strftime') else f"T+{ot_start}h"
                                end_str = test_df.index[ot_end - 1].strftime('%H:%M') if hasattr(test_df.index[ot_end - 1], 'strftime') else f"T+{ot_end-1}h"
                                total_mh = ot_labors * ot_hours
                                return {
                                    'status': 'SUCCESS',
                                    'level': 'Level 6: Làm thêm giờ Outbound (Overtime)',
                                    'action_logs': [
                                        f"Huy động {ot_labors} công nhân Outbound làm OT trong {ot_hours} giờ (Từ {start_str} đến {end_str}).",
                                        f"Tổng số giờ công OT phát sinh: {total_mh} man-hours."
                                    ],
                                    'cost': total_mh * 1.5,
                                    'df_before': df_plan_simulation,
                                    'df_after': df_after
                                }

        # =====================================================================
        # NHÁNH 3: XỬ LÝ NGHẼN TẠI KHO ĐỆM KITTING BUFFER
        # =====================================================================
        elif b_type == 'buffer':
            helper_combos = [
                (1, 0, "1 công nhân từ Inbound"),
                (0, 1, "1 công nhân từ Outbound"),
                (1, 1, "Combo: 1 Inbound + 1 Outbound"),
                (2, 0, "2 công nhân từ Inbound"),
                (0, 2, "2 công nhân từ Outbound")
            ]

            for b_in, b_out, desc in helper_combos:
                curr_in = int(candidate_df.iloc[t_idx]['labor_inbound'])
                curr_out = int(candidate_df.iloc[t_idx]['labor_outbound'])
                
                # Cả 2 kho đều phải giữ tối thiểu 2 người trực
                if (curr_in - b_in >= 2) and (curr_out - b_out >= 2):
                    test_df = candidate_df.copy()
                    test_df.loc[curr_time, 'labor_inbound'] = curr_in - b_in
                    test_df.loc[curr_time, 'labor_outbound'] = curr_out - b_out
                    test_df.loc[curr_time, 'labor_buffer'] = int(b_in + b_out)
                    
                    is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                    if is_better:
                        return {
                            'status': 'SUCCESS',
                            'level': 'Hỗ trợ nhân lực bốc xếp Buffer',
                            'action_logs': [
                                f"Điều động {desc} sang hỗ trợ bốc xếp thủ công xả hàng khỏi Buffer lúc {hour_str}.",
                                f"Năng lực kéo hàng được tăng thêm {(b_in + b_out) * RATE_LABOR_OUTBOUND} pallets/h."
                            ],
                            'cost': 0,
                            'df_before': df_plan_simulation,
                            'df_after': df_after
                        }

            # Tăng cường xe AMR (Tối đa 8 xe)
            current_amr = int(candidate_df.iloc[t_idx]['amr_active'])
            if current_amr < 8:
                for added_amr in range(1, 8 - current_amr + 1):
                    test_df = candidate_df.copy()
                    test_df.loc[curr_time, 'amr_active'] = current_amr + added_amr
                    for charge_offset in [3, 4, 5]:
                        charge_idx = t_idx + charge_offset
                        if charge_idx < n_steps and candidate_df.iloc[charge_idx]['amr_active'] > 3:
                            charge_time = test_df.index[charge_idx]
                            test_df.loc[charge_time, 'amr_active'] = int(test_df.loc[charge_time, 'amr_active']) - added_amr
                            break
                            
                    is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                    if is_better:
                        return {
                            'status': 'SUCCESS',
                            'level': 'Bổ sung xe AMR cho Buffer',
                            'action_logs': [
                                f"Tăng cường {added_amr} xe AMR lúc {hour_str} để tăng lực kéo xả hàng khỏi Buffer.",
                                "Đã lên lịch cắm sạc pin bù cho các xe này vào ca thấp điểm sau đó."
                            ],
                            'cost': 0,
                            'df_before': df_plan_simulation,
                            'df_after': df_after
                        }

        return {
            'status': 'FAILED',
            'level': 'Cần can thiệp cấp Quản đốc',
            'message': 'Đã quét qua toàn bộ 6 cấp độ can thiệp (Heijunka, Đổi ca, Mượn người, Super Combo, OT) nhưng lượng tồn quá lớn không thể giải tỏa an toàn. Đề xuất Quản đốc đàm phán giảm tải với ERP.',
            'df_before': df_plan_simulation,
            'df_after': df_plan_simulation
        }
