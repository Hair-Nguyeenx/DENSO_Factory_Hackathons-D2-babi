import pandas as pd 
import numpy as np
import copy 

RATE_LABOR_INBOUND = 15.0   # pallets / người / giờ
RATE_LABOR_OUTBOUND = 15.0  # pallets / người / giờ 
RATE_AMR = 14.0             # pallets / xe / giờ
MAX_STORAGE_INBOUND = 200
MAX_STORAGE_BUFFER = 500
MAX_STORAGE_OUTBOUND = 300
# Ngưỡng Vàng (Cảnh báo nghẽn)
WARN_STORAGE_INBOUND = MAX_STORAGE_INBOUND * 0.8  
WARN_STORAGE_BUFFER = MAX_STORAGE_BUFFER * 0.8    
# Ngưỡng Đỏ Outbound (Outbound có thể chịu ngưỡng đỏ chờ xe tải)
WARN_STORAGE_OUTBOUND = MAX_STORAGE_OUTBOUND * 0.9 

class CapacityModelEngine:
    def __init__(self):
        pass
    def simulate_24h(self, df_plan: pd.DataFrame, initial_stocks: tuple):
        df_sim = df_plan.copy()
        s_inbound, s_buffer, s_outbound = initial_stocks
        
        simulating_storage_inbound = []
        simulating_storage_buffer = []
        simulating_storage_outbound = []

        SOFT_CAP_IN = MAX_STORAGE_INBOUND * 2.5
        SOFT_CAP_BUF = MAX_STORAGE_BUFFER * 2.5
        SOFT_CAP_OUT = MAX_STORAGE_OUTBOUND * 2.5
        simulating_storage_inbound = []
        simulating_storage_buffer = []
        simulating_storage_outbound = []
        
        for idx in range(len(df_sim)):
            row = df_sim.iloc[idx]
            w_in = row['workload_inbound']
            w_out = row['workload_outbound']
            labor_in = row['labor_inbound']
            labor_out = row['labor_outbound']
            amr = row['amr_active']
            labor_buf = row['labor_buffer'] if 'labor_buffer' in row else 0
            
            # Lấy giờ thực tế nếu index là datetime, ngược lại lấy index thô
            hour = df_sim.index[idx].hour if hasattr(df_sim.index[idx], 'hour') else idx % 24
            
            # Kho 1: Kho inbound 
            capacity_in = labor_in * RATE_LABOR_INBOUND
            available_in = s_inbound + w_in
            space_in_buffer = max(0, MAX_STORAGE_BUFFER - s_buffer)
            flow_in = int(min(available_in * 0.6, capacity_in, space_in_buffer))

            # Kho 2: Kho buffer
            amr_capacity = (amr * RATE_AMR) + (labor_buf * RATE_LABOR_OUTBOUND)
            target_out = MAX_STORAGE_OUTBOUND * 0.5
            if 20 <= hour or hour <= 5: target_out = MAX_STORAGE_OUTBOUND * 0.8   # Đêm dồn hàng
            elif hour == 6 or hour == 7: target_out = MAX_STORAGE_OUTBOUND * 0.3  # Sáng xả mạnh
            amr_demand = max(0, w_out + (target_out - s_outbound) * 0.5)
            available_buffer = s_buffer + flow_in
            space_in_out = max(0, MAX_STORAGE_OUTBOUND - s_outbound)
            flow_out = min(amr_capacity, space_in_out, amr_demand, available_buffer * 0.7)

            # Kho 3: Kho outbound
            capacity_out = labor_out * RATE_LABOR_OUTBOUND
            truck_demand = w_out
            available_out = s_outbound + flow_out
            ship_out = min(capacity_out, truck_demand, available_out)
            s_inbound = available_in - flow_in
            s_buffer = available_buffer - flow_out
            s_outbound = available_out - ship_out

            # Cắt ngọn vượt giới hạn tuyệt đối (Soft Cap)
            s_inbound = min(s_inbound, SOFT_CAP_IN)
            s_buffer = min(s_buffer, SOFT_CAP_BUF)
            s_outbound = min(s_outbound, SOFT_CAP_OUT)
            simulating_storage_inbound.append(s_inbound)
            simulating_storage_buffer.append(s_buffer)
            simulating_storage_outbound.append(s_outbound)
            
        df_sim['storage_inbound_sim'] = simulating_storage_inbound
        df_sim['storage_buffer_sim'] = simulating_storage_buffer
        df_sim['storage_outbound_sim'] = simulating_storage_outbound
        
        return df_sim

    def scan_bottlenecks(self, df_sim: pd.DataFrame):
        bottlenecks = []
        for idx in range(len(df_sim)):
            row = df_sim.iloc[idx]
            if row['storage_inbound_sim'] >= WARN_STORAGE_INBOUND: 
                bottlenecks.append({
                    'time_index': idx,
                    'hour': df_sim.index[idx].strftime('%H:%M') if hasattr(df_sim.index[idx], 'strftime') else idx,
                    'type': 'inbound',
                    'severity': row['storage_inbound_sim'] - WARN_STORAGE_INBOUND
                })
            elif row['storage_buffer_sim'] >= WARN_STORAGE_BUFFER:
                bottlenecks.append({
                    'time_index': idx,
                    'hour': df_sim.index[idx].strftime('%H:%M') if hasattr(df_sim.index[idx], 'strftime') else idx,
                    'type': 'buffer',
                    'severity': row['storage_buffer_sim'] - WARN_STORAGE_BUFFER
                }
                )
            elif row['storage_outbound_sim'] >= WARN_STORAGE_OUTBOUND:
                bottlenecks.append({
                    'time_index': idx,
                    'hour': df_sim.index[idx].strftime('%H:%M') if hasattr(df_sim.index[idx], 'strftime') else idx,
                    'type': 'outbound',
                    'severity': row['storage_outbound_sim'] - WARN_STORAGE_OUTBOUND
                })
        return bottlenecks    

    def evaluate_plan(self, candidate_df, initial_stocks, original_bottlenecks):
        #Hàm chấm điểm
        simulating_plan = self.simulate_24h(candidate_df, initial_stocks)
        new_bottlenecks = self.scan_bottlenecks(simulating_plan)

        #Nếu không có bottlenecks nào => Giải quyết được vấn đề
        if len(new_bottlenecks) == 0:
            return True, simulating_plan

        return False, None

    def solve_capacity_bottleneck(self, df_plan: pd.DataFrame, initial_stocks:tuple):

        """
        Sử dụng Rule-based Heuristic Search: Phân tích và tìm ra giải pháp tốt nhất
        Ở đây ta có các ưu tiên từ cao tới thấp nhất
        1.Dàn trải phẳng heijunka (Liệu giảm tải workload tại ca t và chia nó cho các ca t-1  có ích không?)
        2.Đổi ca/Điều chuyển nội bộ (Xem là ở ca này bộ phận ở khu khác có rảnh không => điều tới hỗ trợ
        hoặc là chuyển ca của người này sang ca khác)
        3.làm việc OT (Không quá 2h)
        4.Điều thêm xe AMR (Không quá tối đa xe của kho)
        """

        df_plan_simulation = self.simulate_24h(df_plan, initial_stocks)
        df_plan_bottleneck = self.scan_bottlenecks(df_plan_simulation)

        if not df_plan_bottleneck:
            return {
                'status': 'NO_ACTION_NEEDED',
                'message': 'Hệ thống vận hành ổn định trong 24h tới, không có nghẽn.',
                'df_before': df_plan_simulation,
                'df_after': df_plan_simulation
            }

        first_b = df_plan_bottleneck[0]
        t_idx = first_b['time_index']
        hour_str = first_b['hour']
        b_type = first_b['type']
        
        candidate_df = df_plan.copy()

        curr_time = candidate_df.index[t_idx]
        """
        Trường hợp tắc nghẽn ở kho inbound
        """
        #Mức 1. Dàn trải phẳng
        if b_type == 'inbound':
            #tính số hàng có thể dàn trải được 
            shift_w = int(candidate_df.iloc[t_idx]['workload_inbound']* 0.25)
            test_df = candidate_df.copy()
            prev_time = test_df.index[t_idx - 1]
            test_df.loc[curr_time, 'workload_inbound'] = float(test_df.loc[curr_time, 'workload_inbound']) - shift_w
            test_df.loc[prev_time, 'workload_inbound'] = float(test_df.loc[prev_time, 'workload_inbound']) + shift_w

            is_better, df_after = self.evaluate_plan(test_df,initial_stocks, df_plan_bottleneck)
            if is_better:
                    return {
                        'status': 'SUCCESS',
                        'level': ' Dàn trải khối lượng việc',
                        'action_logs': [f"Hẹn nhà xe dời {shift_w} pallets Inbound từ lúc {hour_str} lên sớm 1 tiếng."],
                        'cost': 0,
                        'df_before': df_plan_simulation,
                        'df_after': df_after
                    }

        
        #Mức 2: Đổi ca/Điều chuyển nội bộ
        if b_type == "inbound":
            labor_outbound = test_df.iloc[t_idx]['labor_outbound']

            #Kiểm tra xem có thể lấy labor outbound sang giúp labor inbound được không
            if labor_outbound >= 3:
                for i in range(1,3):
                    test_df = candidate_df.copy()
                    test_df.loc[curr_time, 'labor_outbound'] = int(test_df.loc[curr_time, 'labor_outbound']) - i
                    test_df.loc[curr_time, 'labor_inbound'] = int(test_df.loc[curr_time, 'labor_inbound']) + i
                    is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                    if is_better:
                       return {
                        'status': 'SUCCESS',
                        'level': ' Đổi ca ngang (Cross-docking)',
                        'action_logs': [f"Điều chuyển {i} công nhân từ Outbound sang Inbound lúc {hour_str}."],
                        'cost': 0,
                        'df_before': df_plan_simulation,
                        'df_after': df_after
                       }

        #Combo: Vừa áp dụng heijunka vừa mượn labor outbound (1-2 người)
            for borrow_labor_out in [1,2]:
                        for offset in [-1, 1]:
                            target_idx = t_idx + offset
                            shift_w = int(candidate_df.iloc[t_idx]['workload_inbound']* 0.25)
                            if 0 <= target_idx < len(candidate_df) and shift_w > 0:
                                test_df = candidate_df.copy()
                                outbound_labor = test_df.iloc[t_idx]['labor_outbound']
                                if outbound_labor >= (2 + borrow_labor_out):
                                    target_time = test_df.index[target_idx]
                                    # Heijunka
                                    test_df.loc[curr_time, 'workload_inbound'] = float(test_df.loc[curr_time, 'workload_inbound']) - shift_w
                                    test_df.loc[target_time, 'workload_inbound'] = float(test_df.loc[target_time, 'workload_inbound']) + shift_w
                                    # Mượn người
                                    test_df.loc[curr_time, 'labor_outbound'] = int(test_df.loc[curr_time, 'labor_outbound']) - borrow_labor_out
                                    test_df.loc[curr_time, 'labor_inbound'] = int(test_df.loc[curr_time, 'labor_inbound']) + borrow_labor_out
                                    is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                                    if is_better:
                                        direct = "sớm" if offset == -1 else "muộn"
                                        return {
                                                'status': 'SUCCESS',
                                                'level': 'Combo Inbound (Heijunka + Mượn người)',
                                                'action_logs': [
                                                    f"Hẹn nhà xe dời {shift_w} pallets Inbound từ lúc {hour_str} sang {direct} 1 tiếng.",
                                                    f"Đồng thời điều chuyển {borrow_labor_out} công nhân từ Outbound sang Inbound lúc {hour_str}."
                                                ],
                                                'cost': 0,
                                                'df_before': df_plan_simulation,
                                                'df_after': df_after
                                            }
    
        
                #Đổi ca của các labor inbound trong tầm 8 tiếng
            for offset in [-8,-7,-6,-5,-4,-3,-2,-1, 1,2,3,4,5,6,7,8]:
                    borrow_labor_index = t_idx + offset
                    if 0 <= borrow_labor_index < len(candidate_df):
                        test_df = candidate_df.copy()
                        borrow_labor = test_df.iloc[borrow_labor_index]['labor_inbound']
                        if borrow_labor >= 2:
                            for i in range(1,3):
                                borrow_time = test_df.index[borrow_labor_index]
                                test_df.loc[borrow_time, 'labor_inbound'] = int(test_df.loc[borrow_time, 'labor_inbound']) - i
                                test_df.loc[curr_time, 'labor_inbound'] = int(test_df.loc[curr_time, 'labor_inbound']) + i
                                is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                                if is_better:
                                    borrow_hour_str = test_df.index[borrow_labor_index].strftime('%H:%M') if hasattr(test_df.index[borrow_labor_index], 'strftime') else borrow_labor_index
                                    return {
                                       'status': 'SUCCESS',
                                       'level': 'Đổi ca dọc ',
                                       'action_logs': [f"Điều chuyển {i} công nhân Inbound từ ca {borrow_hour_str} sang ca {hour_str}."],
                                       'cost': 0,
                                       'df_before': df_plan_simulation,
                                       'df_after': df_after
                                    }
     

            #Cấp 3: Làm overtime 
    
            #Số labor làm OT
            for ot_labors in [1,2,3]:
                for ot_hours in [1, 2]:
                #Thời gian bắt đầu OT
                    for offset in [-3, -2, -1,0, 1, 2, 3]:
                        ot_idx_start = t_idx + offset
                        ot_idx_end = ot_idx_start + ot_hours
    
                        if 0 <= ot_idx_start and ot_idx_end <= len(candidate_df):
                            test_df = candidate_df.copy()
                            for h_idx in range(ot_idx_start, ot_idx_end):
                                h_time = test_df.index[h_idx]
                                test_df.loc[h_time, 'labor_inbound'] = int(test_df.loc[h_time, 'labor_inbound']) + ot_labors
                            is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
    
                            if is_better:
                                start_str = test_df.index[ot_idx_start].strftime('%H:%M') if hasattr(test_df.index[ot_idx_start], 'strftime') else ot_idx_start
                                end_str = test_df.index[ot_idx_end - 1].strftime('%H:%M') if hasattr(test_df.index[ot_idx_end - 1], 'strftime') else (ot_idx_end- 1)
                                
                                total_man_hours = ot_labors * ot_hours
                                cost_est = total_man_hours * 1.5  # Hệ số lương OT 1.5x
                                
                                return {
                                    'status': 'SUCCESS',
                                    'level': 'Làm thêm giờ (Overtime)',
                                    'action_logs': [
                                        f"Huy động {ot_labors} công nhân làm OT trong {ot_hours} giờ (Từ {start_str} đến hết {end_str}).",
                                        f"Tổng số giờ công OT phát sinh: {total_man_hours} man-hours."
                                    ],
                                    'cost': cost_est,
                                    'df_before': df_plan_simulation,
                                    'df_after': df_after
                                }
    
        #Trường hợp bị tắc nghẽn ở kho outbound

        elif b_type == "outbound":
            shift_w_out = int(candidate_df.iloc[t_idx]['workload_outbound'] * 0.25)
            curr_labor_capacity_out = candidate_df.iloc[t_idx]['labor_outbound'] * RATE_LABOR_OUTBOUND
            curr_w_out = candidate_df.iloc[t_idx]['workload_outbound']
            for offset in [-1, 1]:
                target_idx = t_idx + offset
                if 0 <= target_idx < len(candidate_df) and shift_w_out > 0:
                    test_df = candidate_df.copy()
                    target_w_out = candidate_df.iloc[target_idx]['workload_outbound']
                    target_labor_capacity_out = candidate_df.iloc[target_idx]['labor_outbound'] * RATE_LABOR_OUTBOUND
                    if target_w_out >  target_labor_capacity_out:
                        pull_req = min(curr_labor_capacity_out - curr_w_out,  shift_w_out)
                        if pull_req > 0:
                           test_df = candidate_df.copy()
                           target_time = test_df.index[target_idx]
                           test_df.loc[curr_time, ['workload_outbound']] = test_df.loc[curr_time, ['workload_outbound']] + pull_req
                           test_df.loc[target_time, ['workload_outbound']] = test_df.loc[target_time, ['workload_outbound']] - pull_req
                           is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                           if is_better:
                               n_str = target_time.strftime('%H:%M') if hasattr(target_time, 'strftime') else target_time
                               return{
                                        'status': 'SUCCESS',
                                        'level': 'Heijunka Outbound',
                                        'action_logs': [f"Thông báo nhà xe tới bốc hàng sớm {pull_req} pallets từ ca {n_str} sang ca {hour_str}."],
                                        'cost': 0,
                                        'df_before': df_plan_simulation,
                                        'df_after': df_after
                                    }

            #Điều chuyển công nhân inbound sang hỗ trợ
            for borrow_laborin in [1, 2]:
                test_df = candidate_df.copy()
                labor_inbound = test_df.iloc[t_idx]['labor_inbound']
                if labor_inbound >= (2+borrow_laborin):
                    test_df.loc[curr_time, ['labor_inbound']] = test_df.loc[curr_time, ['labor_inbound']] - borrow_laborin
                    test_df.loc[curr_time, ['labor_outbound']] = test_df.loc[curr_time, ['labor_outbound']] + borrow_laborin
                    is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                    if is_better:
                         return {
                            'status': 'SUCCESS',
                            'level': 'Điều chuyển labor Inbound sang Outbound',
                            'action_logs': [f"Điều chuyển {borrow_laborin} công nhân từ Inbound sang Outbound lúc {hour_str}."],
                            'cost': 0,
                            'df_before': df_plan_simulation,
                            'df_after': df_after
                        }

            #Combo vừa dàn trải vừa điều chuyển người
            for borrow_laborin in [1,2]:
                for offset in [-1, 1]:
                    target_idx = t_idx + offset
                    if 0 <= target_idx < len(candidate_df) and shift_w_out > 0:
                        test_df = candidate_df.copy()
                        labor_inbound = test_df.iloc[t_idx]['labor_inbound']
                        if labor_inbound >= (2+borrow_laborin):
                            target_time = test_df.index[target_idx]

                            #heijunka 
                            test_df.loc[curr_time, ['workload_outbound']] = test_df.loc[curr_time, ['workload_outbound']] + shift_w_out
                            test_df.loc[target_time, ['workload_outbound']] = test_df.loc[target_time, ['workload_outbound']] - shift_w_out
                            #Dieu chuyen nguoi
                            test_df.loc[curr_time, ['labor_inbound']] = test_df.loc[curr_time, ['labor_inbound']] - borrow_laborin
                            test_df.loc[curr_time, ['labor_outbound']] = test_df.loc[curr_time, ['labor_outbound']] + borrow_laborin

                            is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                            if is_better:
                                return {
                                    'status': 'SUCCESS',
                                    'level': 'Combo Outbound (Heijunka xuất + Mượn người)',
                                    'action_logs': [
                                        f"Thông báo nhà xe gom bớt {shift_w_out} pallets xuất sớm tại {hour_str}.",
                                        f"Đồng thời điều chuyển {borrow_laborin} công nhân từ Inbound sang Outbound để tăng tốc bốc xe."
                                    ],
                                    'cost': 0,
                                    'df_before': df_plan_simulation,
                                    'df_after': df_after
                                }

            for ot_labors in [1, 2, 3]:
                for ot_hours in [1, 2]:
                    for offset in [-3, -2, -1, 0, 1, 2, 3]:
                        ot_start_idx = t_idx + offset
                        ot_end_idx = ot_start_idx + ot_hours
                        if 0 <= ot_start_idx and ot_end_idx <= len(candidate_df):
                            test_df = candidate_df.copy()
                            for h_idx in range(ot_start_idx, ot_end_idx):
                                h_time = test_df.index[h_idx]
                                test_df.loc[h_time, 'labor_outbound'] = int(test_df.loc[h_time, 'labor_outbound']) + ot_labors
                            
                            is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                            if is_better:
                                start_str = test_df.index[ot_start_idx].strftime('%H:%M') if hasattr(test_df.index[ot_start_idx], 'strftime') else ot_start_idx
                                end_str = test_df.index[ot_end_idx - 1].strftime('%H:%M') if hasattr(test_df.index[ot_end_idx - 1], 'strftime') else (ot_end_idx - 1)
                                total_mh = ot_labors * ot_hours
                                return {
                                    'status': 'SUCCESS',
                                    'level': 'Làm thêm giờ Outbound (Overtime)',
                                    'action_logs': [
                                        f"Huy động {ot_labors} công nhân Outbound làm OT trong {ot_hours} giờ (Từ {start_str} đến hết {end_str}).",
                                        f"Tổng số giờ công OT phát sinh: {total_mh} man-hours."
                                    ],
                                    'cost': total_mh * 1.5,
                                    'df_before': df_plan_simulation,
                                    'df_after': df_after
                                } 

        #Xử lí điểm nghẽn tại kho buffer

        elif b_type == "buffer":
            helper_combos = [
                (1, 0, "1 công nhân từ Inbound"),
                (0, 1, "1 công nhân từ Outbound"),
                (1, 1, "Combo: 1 Inbound + 1 Outbound"),
                (2, 0, "2 công nhân từ Inbound"),
                (0, 2, "2 công nhân từ Outbound")
            ]

            for b_in, b_out, desc in helper_combos:
                test_df = candidate_df.copy()
                curr_in = test_df.iloc[t_idx]['labor_inbound']
                curr_out = test_df.iloc[t_idx]['labor_outbound']
                
                # Kiểm tra cả Inbound và Outbound đều phải còn ít nhất 2 người trụ ca
                if (curr_in - b_in >= 2) and (curr_out - b_out >= 2):
                    test_df.loc[curr_time, 'labor_inbound'] = int(curr_in - b_in)
                    test_df.loc[curr_time, 'labor_outbound'] = int(curr_out - b_out)
                    test_df.loc[curr_time, 'labor_buffer'] = int(b_in + b_out)
                    
                    is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                    if is_better:
                        return {
                            'status': 'SUCCESS',
                            'level': ' Hỗ trợ nhân lực bốc xếp Buffer',
                            'action_logs': [
                                f"Điều động {desc} sang hỗ trợ xe AMR bốc hàng thủ công lúc {hour_str}.",
                                f"Năng lực kéo hàng của Buffer được tăng thêm {(b_in + b_out) * RATE_LABOR_OUTBOUND} pallets/h."
                            ],
                            'cost': 0,
                            'df_before': df_plan_simulation,
                            'df_after': df_after
                        }

            #Điều thêm xe AMR (Tối đa 8)
            test_df = candidate_df.copy()
            current_amr = test_df.iloc[t_idx]['amr_active']

            if current_amr < 8:
                for added_amr in range(1, 8-current_amr + 1):
                    test_df.loc[curr_time, 'amr_active'] = int(current_amr) + added_amr
                    for charge_offset in [4, 5, 6]:
                        charge_idx = t_idx + charge_offset
                        if charge_idx < len(test_df) and test_df.iloc[charge_idx]['amr_active'] > 3:
                            charge_time = test_df.index[charge_idx]
                            test_df.loc[charge_time, 'amr_active'] = int(test_df.loc[charge_time, 'amr_active']) - added_amr
                            break
                    is_better, df_after = self.evaluate_plan(test_df, initial_stocks, df_plan_bottleneck)
                    if is_better:
                            return {
                                'status': 'SUCCESS',
                                'level': ' Bổ sung xe AMR cho Buffer',
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
            'level': 'Thất bại',
            'message': 'Đã quét toàn bộ các cấp độ can thiệp nhưng không thể giải phóng điểm nghẽn mà không gây vỡ trận ca khác. Đề xuất Quản đốc can thiệp thủ công.',
            'df_before': df_plan_simulation,
            'df_after': df_plan_simulation
        }

     
            


             
                    

   


        
                

