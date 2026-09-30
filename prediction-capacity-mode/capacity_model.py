import pandas as pd 
import numpy as np
import copy 


# HẰNG SỐ & ĐỊNH MỨC NĂNG LỰC VẬN HÀNH (DENSO LOGISTICS STANDARDS)

RATE_LABOR_INBOUND = 15.0   # pallets / người / giờ
RATE_LABOR_OUTBOUND = 15.0  # pallets / người / giờ 
RATE_AMR = 14.0             # pallets / xe / giờ

MAX_STORAGE_INBOUND = 200
MAX_STORAGE_BUFFER = 500
MAX_STORAGE_OUTBOUND = 300

# Ngưỡng Vàng (Cảnh báo sớm nguy cơ nghẽn kho - 80%)
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
        """Quét và xếp loại các điểm nghẽn vượt ngưỡng an toàn (vạch vàng nét đứt)"""
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

    def calculate_plan_penalty(self, df_sim: pd.DataFrame, action_cost: float = 0.0, disruption_score: float = 0.0) -> float:
        """
        Tính điểm phạt của toàn bộ kịch bản. Điểm càng THẤP thì kịch bản càng TỐT.
        - Vượt ngưỡng vàng: phạt x1
        - Vượt trần đỏ: phạt x5 (ngăn chặn vỡ trần kho)
        - Chi phí OT: phạt x3
        - Độ xáo trộn điều chuyển: phạt x1
        """
        storage_penalty = 0.0
        for idx in range(len(df_sim)):
            row = df_sim.iloc[idx]
            
            # 1. Inbound
            s_in = row['storage_inbound_sim']
            if s_in > MAX_STORAGE_INBOUND:
                storage_penalty += (MAX_STORAGE_INBOUND - WARN_STORAGE_INBOUND) * 1.0 + (s_in - MAX_STORAGE_INBOUND) * 5.0
            elif s_in > WARN_STORAGE_INBOUND:
                storage_penalty += (s_in - WARN_STORAGE_INBOUND) * 1.0
                
            # 2. Buffer
            s_buf = row['storage_buffer_sim']
            if s_buf > MAX_STORAGE_BUFFER:
                storage_penalty += (MAX_STORAGE_BUFFER - WARN_STORAGE_BUFFER) * 1.0 + (s_buf - MAX_STORAGE_BUFFER) * 5.0
            elif s_buf > WARN_STORAGE_BUFFER:
                storage_penalty += (s_buf - WARN_STORAGE_BUFFER) * 1.0
                
            # 3. Outbound
            s_out = row['storage_outbound_sim']
            if s_out > MAX_STORAGE_OUTBOUND:
                storage_penalty += (MAX_STORAGE_OUTBOUND - WARN_STORAGE_OUTBOUND) * 1.0 + (s_out - MAX_STORAGE_OUTBOUND) * 5.0
            elif s_out > WARN_STORAGE_OUTBOUND:
                storage_penalty += (s_out - WARN_STORAGE_OUTBOUND) * 1.0

        total_penalty = (storage_penalty * 10.0) + (action_cost * 3.0) + (disruption_score * 1.0)
        return round(total_penalty, 2)

    def solve_capacity_bottleneck(self, df_plan: pd.DataFrame, initial_stocks: tuple, max_iterations: int = 6):
        """
        THUẬT TOÁN TỐI ƯU HÓA LẶP (ITERATIVE HEURISTIC OPTIMIZATION) DỰA TRÊN HÀM PHẠT:
        - Giải quyết triệt để chuỗi nghẽn kéo dài nhiều ca / nhiều giờ liên tục.
        - Dàn trải tải Heijunka đa khung giờ (t-1, t-2, t-3, t+1, t+2) với nhiều mức tỷ lệ.
        - Phối hợp đa hành động: Heijunka + Mượn ngang + Đổi ca dọc + OT + Điều xe AMR.
        - Không bị 'thành công ảo', đánh giá mức độ giảm áp lực (%) và chỉ rõ phần tồn đọng còn lại.
        """
        current_df = df_plan.copy()
        if 'labor_buffer' not in current_df.columns:
            current_df['labor_buffer'] = 0.0
            
        current_sim = self.simulate_24h(current_df, initial_stocks)
        current_penalty = self.calculate_plan_penalty(current_sim)
        initial_penalty = current_penalty
        
        initial_bottlenecks = self.scan_bottlenecks(current_sim)
        if not initial_bottlenecks or current_penalty == 0:
            return {
                'status': 'NO_ACTION_NEEDED',
                'level': 'Vận hành tối ưu',
                'message': 'Hệ thống vận hành an toàn trong tầm nhìn dự báo, không có nguy cơ nghẽn kho.',
                'action_logs': ['Không cần can thiệp.'],
                'cost': 0.0,
                'penalty_reduction_pct': 0.0,
                'initial_penalty': 0.0,
                'final_penalty': 0.0,
                'remaining_bottlenecks': [],
                'df_before': current_sim,
                'df_after': current_sim
            }

        actions_taken = []
        total_cost = 0.0
        n_steps = len(current_df)

        # VÒNG LẶP TỐI ƯU HÓA ĐA BƯỚC
        for step in range(max_iterations):
            bns = self.scan_bottlenecks(current_sim)
            if not bns:
                break # Đã giải phóng hoàn toàn tất cả điểm nghẽn

            # Ưu tiên giải quyết điểm nghẽn phát sinh sớm nhất theo trục thời gian (Root Cause)
            # để dập tắt ngay từ gốc, ngăn chặn hiệu ứng tích lũy tồn kho lan truyền sang các ca sau
            bns_sorted = sorted(bns, key=lambda x: (x['time_index'], -x['severity']))
            worst_b = bns_sorted[0]
            t_idx = worst_b['time_index']
            hour_str = worst_b['hour']
            b_type = worst_b['type']
            curr_time = current_df.index[t_idx]

            best_candidate_df = None
            best_candidate_sim = None
            best_candidate_penalty = current_penalty
            best_action_desc = ""
            best_action_cost = 0.0

            candidates = []

            if b_type == 'inbound':
                w_in = float(current_df.loc[curr_time, 'workload_inbound'])
                
                # 1. Micro-Heijunka Inbound (Thử dời 15%, 25%, 35%, 50% sang các ca lân cận)
                for ratio in [0.15, 0.25, 0.35, 0.50]:
                    shift_w = int(w_in * ratio)
                    if shift_w <= 0: continue
                      # Chỉ quét các ca tương lai ở phía trước trong khung dự báo: t-1, t-2, t-3, t-4, t-5
                    for offset in [-1, -2, -3, -4, -5]:
                        target_idx = t_idx + offset
                        if 0 <= target_idx < n_steps:
                            test_df = current_df.copy()
                            target_time = test_df.index[target_idx]
                            test_df.loc[curr_time, 'workload_inbound'] -= shift_w
                            test_df.loc[target_time, 'workload_inbound'] += shift_w
                            
                            direct_str = f"sớm {-offset}h ({test_df.index[target_idx].strftime('%H:%M') if hasattr(test_df.index[target_idx], 'strftime') else f'T{offset}h'})"
                            candidates.append({
                                'df': test_df,
                                'desc': f"Heijunka Inbound (Kéo sớm): Đàm phán giao sớm {shift_w} pallets từ {hour_str} về ca trước {direct_str}.",
                                'cost': 0.0,
                                'disruption': 0.3 * abs(offset)
                            })

                # 2. Điều chuyển ngang (Cross-dock labor: Outbound -> Inbound)
                labor_out = int(current_df.loc[curr_time, 'labor_outbound'])
                for borrow in [1, 2, 3]:
                    if labor_out - borrow >= 1: # Outbound giữ lại ít nhất 1 người
                        test_df = current_df.copy()
                        test_df.loc[curr_time, 'labor_outbound'] -= borrow
                        test_df.loc[curr_time, 'labor_inbound'] += borrow
                        candidates.append({
                            'df': test_df,
                            'desc': f"Điều động {borrow} công nhân Outbound -> Inbound lúc {hour_str}.",
                            'cost': 0.0,
                            'disruption': 0.6 * borrow
                        })

                # 3. Đổi ca dọc nội bộ (Shift Swap: huy động người từ ca thấp điểm cùng ngày)
                for offset in range(-6, 7):
                    if offset == 0: continue
                    donor_idx = t_idx + offset
                    if 0 <= donor_idx < n_steps:
                        donor_time = current_df.index[donor_idx]
                        if current_df.loc[donor_time, 'labor_inbound'] >= 3:
                            for borrow in [1, 2]:
                                test_df = current_df.copy()
                                test_df.loc[donor_time, 'labor_inbound'] -= borrow
                                test_df.loc[curr_time, 'labor_inbound'] += borrow
                                s_str = donor_time.strftime('%H:%M') if hasattr(donor_time, 'strftime') else f"T{offset}h"
                                candidates.append({
                                    'df': test_df,
                                    'desc': f"Đổi ca dọc: Chuyển {borrow} công nhân Inbound từ ca thấp {s_str} sang ca cao điểm {hour_str}.",
                                    'cost': 0.0,
                                    'disruption': 0.5 * borrow
                                })

                # 4. Làm thêm giờ (OT Inbound)
                for ot_labors in [1, 2, 3]:
                    for ot_dur in [1, 2]:
                        test_df = current_df.copy()
                        for h in range(ot_dur):
                            ot_idx = t_idx + h
                            if ot_idx < n_steps:
                                ot_time = test_df.index[ot_idx]
                                test_df.loc[ot_time, 'labor_inbound'] += ot_labors
                        cost_est = ot_labors * ot_dur * 1.5
                        candidates.append({
                            'df': test_df,
                            'desc': f"Huy động {ot_labors} công nhân Inbound làm OT {ot_dur}h tại {hour_str}.",
                            'cost': cost_est,
                            'disruption': 2.0
                        })

            elif b_type == 'outbound':
                w_out = float(current_df.loc[curr_time, 'workload_outbound'])
                
                # 1. Heijunka Outbound
                for ratio in [0.15, 0.25, 0.35]:
                    shift_w = int(w_out * ratio)
                    if shift_w <= 0: continue
                    # Ưu tiên điều xe lấy hàng sớm ở các ca trước (offset < 0)
                    for offset in [-1, -2, -3]:
                        target_idx = t_idx + offset
                        if 0 <= target_idx < n_steps:
                            test_df = current_df.copy()
                            target_time = test_df.index[target_idx]
                            test_df.loc[curr_time, 'workload_outbound'] -= shift_w
                            test_df.loc[target_time, 'workload_outbound'] += shift_w
                            direct_str = f"sớm {-offset}h ({test_df.index[target_idx].strftime('%H:%M') if hasattr(test_df.index[target_idx], 'strftime') else f'T{offset}h'})"
                            candidates.append({
                                'df': test_df,
                                'desc': f"Heijunka Outbound: Điều xe bốc sớm {shift_w} pallets Outbound {direct_str} tại {hour_str}.",
                                'cost': 0.0,
                                'disruption': 0.3 * abs(offset)
                            })

                # 2. Điều chuyển ngang (Inbound -> Outbound)
                labor_in = int(current_df.loc[curr_time, 'labor_inbound'])
                for borrow in [1, 2]:
                    if labor_in - borrow >= 1:
                        test_df = current_df.copy()
                        test_df.loc[curr_time, 'labor_inbound'] -= borrow
                        test_df.loc[curr_time, 'labor_outbound'] += borrow
                        candidates.append({
                            'df': test_df,
                            'desc': f"Điều chuyển {borrow} công nhân Inbound -> Outbound lúc {hour_str}.",
                            'cost': 0.0,
                            'disruption': 0.6 * borrow
                        })

                # 3. Làm thêm giờ (OT Outbound)
                for ot_labors in [1, 2, 3]:
                    for ot_dur in [1, 2]:
                        test_df = current_df.copy()
                        for h in range(ot_dur):
                            ot_idx = t_idx + h
                            if ot_idx < n_steps:
                                ot_time = test_df.index[ot_idx]
                                test_df.loc[ot_time, 'labor_outbound'] += ot_labors
                        cost_est = ot_labors * ot_dur * 1.5
                        candidates.append({
                            'df': test_df,
                            'desc': f"Huy động {ot_labors} công nhân Outbound làm OT {ot_dur}h tại {hour_str}.",
                            'cost': cost_est,
                            'disruption': 2.0
                        })

            elif b_type == 'buffer':
                # 1. Tăng cường nhân lực hỗ trợ bốc xếp Buffer
                curr_in = int(current_df.loc[curr_time, 'labor_inbound'])
                curr_out = int(current_df.loc[curr_time, 'labor_outbound'])
                for b_in, b_out, desc in [(1, 0, "1 Inbound"), (0, 1, "1 Outbound"), (1, 1, "1 Inbound + 1 Outbound")]:
                    if (curr_in - b_in >= 1) and (curr_out - b_out >= 1):
                        test_df = current_df.copy()
                        test_df.loc[curr_time, 'labor_inbound'] -= b_in
                        test_df.loc[curr_time, 'labor_outbound'] -= b_out
                        test_df.loc[curr_time, 'labor_buffer'] = int(test_df.loc[curr_time, 'labor_buffer']) + (b_in + b_out)
                        candidates.append({
                            'df': test_df,
                            'desc': f"Điều động {desc} sang hỗ trợ bốc dỡ xả kho Buffer lúc {hour_str}.",
                            'cost': 0.0,
                            'disruption': 0.5 * (b_in + b_out)
                        })

                # 2. Điều thêm xe AMR
                curr_amr = int(current_df.loc[curr_time, 'amr_active'])
                if curr_amr < 8:
                    for add_amr in [1, 2]:
                        if curr_amr + add_amr <= 8:
                            test_df = current_df.copy()
                            test_df.loc[curr_time, 'amr_active'] += add_amr
                            # Lên lịch sạc bù
                            for c_off in [3, 4, 5]:
                                c_idx = t_idx + c_off
                                if c_idx < n_steps and current_df.iloc[c_idx]['amr_active'] > 3:
                                    c_time = test_df.index[c_idx]
                                    test_df.loc[c_time, 'amr_active'] -= add_amr
                                    break
                            candidates.append({
                                'df': test_df,
                                'desc': f"Bổ sung {add_amr} xe AMR tăng lực xả kho Buffer lúc {hour_str}.",
                                'cost': 0.0,
                                'disruption': 0.2
                            })

            # --- ĐÁNH GIÁ TẤT CẢ CÁC CANDIDATE ---
            for cand in candidates:
                sim = self.simulate_24h(cand['df'], initial_stocks)
                penalty = self.calculate_plan_penalty(sim, cand['cost'], cand['disruption'])
                if penalty < best_candidate_penalty:
                    best_candidate_penalty = penalty
                    best_candidate_df = cand['df']
                    best_candidate_sim = sim
                    best_action_desc = cand['desc']
                    best_action_cost = cand['cost']

            # Cập nhật bước đi tối ưu nhất
            if best_candidate_df is not None:
                current_df = best_candidate_df
                current_sim = best_candidate_sim
                current_penalty = best_candidate_penalty
                actions_taken.append(best_action_desc)
                total_cost += best_action_cost
            else:
                # Không còn hành động nào có thể giảm phạt thêm nữa
                break

        # TỔNG KẾT KẾT QUẢ ĐIỀU ĐỘ
        final_bottlenecks = self.scan_bottlenecks(current_sim)
        penalty_reduction = (initial_penalty - current_penalty) / initial_penalty * 100 if initial_penalty > 0 else 0

        if len(final_bottlenecks) == 0:
            status = 'SUCCESS'
            level = f"Triệt tiêu 100% điểm nghẽn ({len(actions_taken)} hành động phối hợp)"
            msg = f"Đã giải quyết TRIỆT ĐỂ toàn bộ điểm nghẽn! (Giảm {penalty_reduction:.1f}% điểm phạt)."
        elif penalty_reduction >= 40.0:
            status = 'SUCCESS'
            level = f"Giảm tải hiệu quả {penalty_reduction:.1f}% ({len(actions_taken)} hành động phối hợp)"
            msg = f"Đã hạ nhiệt {penalty_reduction:.1f}% mức độ nghiêm trọng. Còn {len(final_bottlenecks)} mốc giờ tồn nhẹ cần giám sát."
        else:
            status = 'MANUAL_REQUIRED'
            level = 'Cần can thiệp cấp Quản đốc'
            msg = f"Điểm nghẽn quá tải cấu trúc (chỉ giảm được {penalty_reduction:.1f}%). Cần Quản đốc đàm phán giảm tải với ERP."

        return {
            'status': status,
            'level': level,
            'message': msg,
            'action_logs': actions_taken if actions_taken else ['Hệ thống vận hành an toàn.'],
            'cost': total_cost,
            'initial_penalty': initial_penalty,
            'final_penalty': current_penalty,
            'penalty_reduction_pct': round(penalty_reduction, 1),
            'remaining_bottlenecks': final_bottlenecks,
            'df_before': self.simulate_24h(df_plan, initial_stocks),
            'df_after': current_sim
        }
