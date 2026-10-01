import os
import numpy as np 
import pandas as pd 
import joblib
from sklearn.metrics import mean_absolute_error, mean_squared_error
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')

# Tự động định vị thư mục chứa file code hiện tại để không bao giờ bị lỗi 'No such file or directory'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def resolve_path(filename):
    if os.path.isabs(filename) and os.path.exists(filename):
        return filename
    if os.path.exists(filename):
        return filename
    p_base = os.path.join(BASE_DIR, filename)
    if os.path.exists(p_base):
        return p_base
    p_parent = os.path.join(os.path.dirname(BASE_DIR), filename)
    if os.path.exists(p_parent):
        return p_parent
    return p_base

#  HẰNG SỐ & ĐỊNH MỨC NĂNG LỰC (ĐỒNG BỘ 100% VỚI CAPACITY_MODEL.PY)

RATE_LABOR_INBOUND = 15.0   # pallets / người / giờ
RATE_LABOR_OUTBOUND = 15.0  # pallets / người / giờ 
RATE_AMR = 14.0             # pallets / xe / giờ

MAX_STORAGE_INBOUND = 200
MAX_STORAGE_BUFFER = 500
MAX_STORAGE_OUTBOUND = 300

WARN_STORAGE_INBOUND = MAX_STORAGE_INBOUND * 0.8   # 160
WARN_STORAGE_BUFFER = MAX_STORAGE_BUFFER * 0.8     # 400
WARN_STORAGE_OUTBOUND = MAX_STORAGE_OUTBOUND * 0.8  # 240 (Đồng bộ chuẩn 80% với capacity_model)


#  HÀM TẠO FEATURE (CHUẨN THEO ĐỊNH HƯỚNG GỐC CỦA BẠN)

def get_shift_code(hour):
    if hour >= 20 or hour <= 5: return 0
    if hour in [6, 7]: return 1
    if 8 <= hour <= 10: return 2
    if 11 <= hour <= 12: return 3
    if 14 <= hour <= 16: return 4
    return 5


def workload_lag_feature(df, target_cols):
    feature = pd.DataFrame(index=df.index)
    y = df[target_cols]
    
    # Biến trễ theo giờ
    for lag, name in [(1, '1h'), (2, '2h'), (3, '3h'), (4, '4h'), (12, '12h'), (18, '18h'),
                      (24, '24h'), (72, '3d'), (168, '7d')]:
        feature[f'lag_{name}'] = y.shift(lag)
        
    # Biến trễ trung bình trượt
    for average, name in [(3, '3h'), (6, '6h'), (12, '12h'), (24, '24h')]:
        feature[f'rollmean_{name}'] = y.shift(1).rolling(average).mean()

    # Biến động ngắn hạn
    feature['spike_ratio_1h_3h'] = (y.shift(1) + 1) / (y.shift(3) + 1)
    feature['diff_1h_2h'] = y.shift(1) - y.shift(2)
    feature['rollmax_24h'] = y.shift(1).rolling(24).max()
    feature['ratio_to_rollmean_6h'] = (y.shift(1) + 1) / (feature['rollmean_6h'] + 1)

    feature['hour'] = df.index.hour
    feature['dayofweek'] = df.index.dayofweek
    feature['month'] = df.index.month
    feature['is_weekend'] = (df.index.dayofweek >= 5).astype(int)

    hours = df.index.hour
    shift_code = np.zeros(len(df), dtype=int)
    shift_code[(hours >= 20) | (hours <= 5)] = 0
    shift_code[(hours == 6) | (hours == 7)] = 1
    shift_code[(hours >= 8) & (hours <= 10)] = 2
    shift_code[(hours >= 11) & (hours <= 12)] = 3
    shift_code[(hours >= 14) & (hours <= 16)] = 4
    shift_code[(hours == 13) | ((hours >= 17) & (hours <= 19))] = 5
    feature['shift_pattern'] = shift_code
    feature['target'] = y
    return feature



#  CƠ CHẾ SỬA SAI THỜI GIAN THỰC CHO 1H (CODE GỐC)

def adaptive_prediction_in_real_time(model, X_test, y_test, alpha=0.35):
    raw_preds = model.predict(X_test)
    adapted_preds = []
    current_bias = 0.0

    for i in range(len(raw_preds)):
        base_pred = raw_preds[i]
        final_p = max(0, base_pred + current_bias)
        adapted_preds.append(final_p)
        
        # Quan sát sai số tại thời điểm t để sửa ngay cho t+1
        actual_workload = y_test.iloc[i]
        error = actual_workload - base_pred
        current_bias = alpha * error + (1 - alpha) * current_bias

    return pd.Series(adapted_preds, index=X_test.index)



# CLASS DỰ BÁO CHO CONTROL ROOM (ĐẦY ĐỦ 3 NÚT: 1H / 3H / 12H VÀ CAPACITY MODEL)

class WarehouseForecaster:
    """
    Module dự báo đa khung giờ phục vụ Control Room:
      - Nút 1h: Sửa sai tức thời (Single EMA)
      - Nút 3h: Sửa sai trung bình khử nhiễu (Window Mean K=6)
      - Nút 12h: Sửa sai theo ca làm việc (Shift Bias)
      - Khớp nối trực tiếp: get_plan_for_capacity_model(...)
    """
    def __init__(self, data_path="denso_logistics_simulation_test.csv"):
        actual_data_path = resolve_path(data_path)
        self.df = pd.read_csv(actual_data_path)
        self.df['timestamp'] = pd.to_datetime(self.df['timestamp'])
        self.df.set_index('timestamp', inplace=True)
        self.df = self.df.asfreq('h')

        self.model_inbound = joblib.load(resolve_path('model_inbound.pkl'))
        self.model_outbound = joblib.load(resolve_path('model_outbound.pkl'))
        self.feature_cols_dict = joblib.load(resolve_path('model_features.pkl'))

        # Bộ nhớ sai số thích ứng (Adaptive Trackers)
        self.bias_1h_in = 0.0
        self.bias_1h_out = 0.0
        self.error_history_in = []
        self.error_history_out = []
        self.shift_bias_in = {b: 0.0 for b in range(6)}
        self.shift_bias_out = {b: 0.0 for b in range(6)}

        # Tính độ lệch chuẩn lịch sử theo giờ (để vẽ dải an toàn Upper 90%)
        train_2026 = self.df.loc['2026']
        self.std_in = train_2026.groupby(train_2026.index.hour)['workload_inbound'].std()
        self.std_out = train_2026.groupby(train_2026.index.hour)['workload_outbound'].std()

    def sync_bias_up_to(self, current_time, warmup_hours=48):
        """
        Tự động đồng bộ hóa bộ nhớ sai số thích ứng (Online Adaptive Bias)
        từ các giờ thực tế gần nhất trước current_time.
        Giúp mô hình nhận diện ngay lập tức khi bước vào đợt Volume Spike (+60%)
        và cộng bù bias vào tương lai, đẩy dự báo lên 120-160 pallets/h.
        """
        self.bias_1h_in = 0.0
        self.bias_1h_out = 0.0
        self.error_history_in = []
        self.error_history_out = []
        self.shift_bias_in = {b: 0.0 for b in range(6)}
        self.shift_bias_out = {b: 0.0 for b in range(6)}

        start_warmup = max(self.df.index[168], current_time - pd.Timedelta(hours=warmup_hours))
        for t in pd.date_range(start_warmup, current_time, freq='h'):
            self.update_actual_at_hour(t)

    def update_actual_at_hour(self, current_time, intervention_delta_in=0.0, intervention_delta_out=0.0):
        """
        Cập nhật sai số thực tế khi vừa bước qua một mốc giờ mới.
        - intervention_delta_in/out: Lượng hàng dời do con người can thiệp (Heijunka).
        - TÁCH BIỆT DỮ LIỆU: Phải trừ đi lượng can thiệp này để mô hình chỉ học sai số dòng chảy tự nhiên,
          tránh hiện tượng bias tăng vọt bất thường (feedback confounding).
        """
        if current_time not in self.df.index:
            return

        # Nhu cầu thực tế tự nhiên (đã bóc tách can thiệp Heijunka)
        act_in = int(self.df.loc[current_time, 'workload_inbound']) - intervention_delta_in
        act_out = int(self.df.loc[current_time, 'workload_outbound']) - intervention_delta_out
        shift_b = get_shift_code(current_time.hour)

        feat_in = self._build_single_feature('workload_inbound', current_time)
        feat_out = self._build_single_feature('workload_outbound', current_time)

        raw_in = self.model_inbound.predict(pd.DataFrame([feat_in])[self.feature_cols_dict['workload_inbound']])[0]
        raw_out = self.model_outbound.predict(pd.DataFrame([feat_out])[self.feature_cols_dict['workload_outbound']])[0]

        err_in = act_in - raw_in
        err_out = act_out - raw_out

        # 1. Single EMA phản ứng tức thời (Kèm kẹp biên an toàn chống nổ bias)
        new_bias_in = 0.40 * err_in + 0.60 * self.bias_1h_in
        new_bias_out = 0.40 * err_out + 0.60 * self.bias_1h_out
        self.bias_1h_in = float(np.clip(new_bias_in, -35.0, 35.0))
        self.bias_1h_out = float(np.clip(new_bias_out, -35.0, 35.0))

        # 2. Lịch sử sai số gần nhất
        self.error_history_in.append(err_in)
        self.error_history_out.append(err_out)
        if len(self.error_history_in) > 24:
            self.error_history_in.pop(0)
            self.error_history_out.pop(0)

        # 3. Shift Bias theo từng ca làm việc (Có kẹp biên chống đột biến ảo)
        new_sb_in = 0.35 * err_in + 0.65 * self.shift_bias_in[shift_b]
        new_sb_out = 0.35 * err_out + 0.65 * self.shift_bias_out[shift_b]
        self.shift_bias_in[shift_b] = float(np.clip(new_sb_in, -25.0, 25.0))
        self.shift_bias_out[shift_b] = float(np.clip(new_sb_out, -25.0, 25.0))

    def _build_single_feature(self, target_col, target_time, y_history=None):
        if y_history is None:
            hist_start = target_time - pd.Timedelta(hours=168)
            hist_end = target_time - pd.Timedelta(hours=1)
            y_s = self.df.loc[hist_start:hist_end, target_col]
        else:
            y_s = y_history

        l1 = y_s.iloc[-1]
        l2 = y_s.iloc[-2]
        l3 = y_s.iloc[-3]
        rm6 = y_s.iloc[-6:].mean()
        hour = target_time.hour

        n = len(y_s)
        lag_4 = y_s.iloc[-4] if n >= 4 else y_s.iloc[0]
        lag_12 = y_s.iloc[-12] if n >= 12 else y_s.iloc[0]
        lag_18 = y_s.iloc[-18] if n >= 18 else y_s.iloc[0]
        lag_24 = y_s.iloc[-24] if n >= 24 else y_s.iloc[0]
        lag_72 = y_s.iloc[-72] if n >= 72 else y_s.iloc[0]
        lag_168 = y_s.iloc[-168] if n >= 168 else y_s.iloc[0]

        return {
            'lag_1h': l1, 'lag_2h': l2, 'lag_3h': l3,
            'lag_4h': lag_4, 'lag_12h': lag_12,
            'lag_18h': lag_18, 'lag_24h': lag_24,
            'lag_3d': lag_72, 'lag_7d': lag_168,
            'rollmean_3h': y_s.iloc[-3:].mean(), 'rollmean_6h': rm6,
            'rollmean_12h': y_s.iloc[-12:].mean(), 'rollmean_24h': y_s.iloc[-24:].mean(),
            'spike_ratio_1h_3h': (l1 + 1) / (l3 + 1),
            'diff_1h_2h': l1 - l2,
            'rollmax_24h': y_s.iloc[-24:].max(),
            'ratio_to_rollmean_6h': (l1 + 1) / (rm6 + 1),
            'hour': hour, 'dayofweek': target_time.dayofweek, 'month': target_time.month,
            'is_weekend': int(target_time.dayofweek >= 5),
            'shift_pattern': get_shift_code(hour)
        }

    def predict_horizon(self, current_time, horizon=1):
        """
        Dự báo chuỗi thời gian liên tục từng giờ [t+1 ... t+horizon]:
        - horizon=1:  Dự báo 1 giờ tới (Nút 1h)
        - horizon=3:  Dự báo chuỗi 3 giờ tới (Nút 3h)
        - horizon=12: Dự báo chuỗi 12 giờ tới (Nút 12h)
        """
        future_idx = pd.date_range(current_time + pd.Timedelta(hours=1), periods=horizon, freq='h')
        
        hist_start = current_time - pd.Timedelta(hours=168)
        y_sim_in = self.df.loc[hist_start:current_time, 'workload_inbound'].copy()
        y_sim_out = self.df.loc[hist_start:current_time, 'workload_outbound'].copy()

        preds_in, preds_out = [], []
        upper_in, upper_out = [], []

        for step, next_t in enumerate(future_idx):
            feat_in = self._build_single_feature('workload_inbound', next_t, y_sim_in)
            feat_out = self._build_single_feature('workload_outbound', next_t, y_sim_out)

            X_in = pd.DataFrame([feat_in])[self.feature_cols_dict['workload_inbound']]
            X_out = pd.DataFrame([feat_out])[self.feature_cols_dict['workload_outbound']]

            raw_in = self.model_inbound.predict(X_in)[0]
            raw_out = self.model_outbound.predict(X_out)[0]

            # Áp dụng cơ chế bias thích ứng nhanh khi có Volume Spike
            decay = max(0.4, 1.0 - step * 0.05)
            if horizon == 1:
                b_in = self.bias_1h_in
                b_out = self.bias_1h_out
            elif horizon <= 3:
                # 3h: kết hợp EMA tức thời với decay nhẹ để giữ đà spike
                b_in = self.bias_1h_in * decay
                b_out = self.bias_1h_out * decay
            else:
                # 12h/24h: ca hiện tại dùng bias EMA, các ca sau kết hợp Shift Bias
                sb = get_shift_code(next_t.hour)
                b_in = max(self.shift_bias_in[sb], self.bias_1h_in * decay)
                b_out = max(self.shift_bias_out[sb], self.bias_1h_out * decay)

            p_in = max(0, raw_in + b_in)
            p_out = max(0, raw_out + b_out)

            # Dải an toàn Upper Bound 90%
            std_val_in = self.std_in.get(next_t.hour, 12.0)
            std_val_out = self.std_out.get(next_t.hour, 15.0)
            uncertainty = np.sqrt(max(0.2, step + 1))
            u_in = p_in + 1.28 * std_val_in * uncertainty
            u_out = p_out + 1.28 * std_val_out * uncertainty

            preds_in.append(round(p_in, 1))
            preds_out.append(round(p_out, 1))
            upper_in.append(round(u_in, 1))
            upper_out.append(round(u_out, 1))

            y_sim_in.loc[next_t] = p_in
            y_sim_out.loc[next_t] = p_out


        return pd.DataFrame({
            'pred_workload_inbound': preds_in,
            'pred_workload_outbound': preds_out,
            'upper_90_inbound': upper_in,
            'upper_90_outbound': upper_out
        }, index=future_idx)

    # HÀM BẮT BUỘC: ĐẦU RA KẾT NỐI TRỰC TIẾP VỚI CAPACITY_MODEL.PY

    def get_plan_for_capacity_model(self, current_time, horizon=12, initial_stocks=None):
        """
        Chuẩn bị DataFrame `df_plan` và `initial_stocks` theo đúng định dạng
        mà CapacityModelEngine (simulate_24h, solve_capacity_bottleneck) yêu cầu.
        """
        # 1. Dự báo workload cho horizon tiếp theo
        df_pred = self.predict_horizon(current_time, horizon=horizon)
        future_idx = df_pred.index

        # 2. Khởi tạo df_plan đúng 5 cột
        df_plan = pd.DataFrame(index=future_idx)
        df_plan['workload_inbound'] = df_pred['pred_workload_inbound'].values
        df_plan['workload_outbound'] = df_pred['pred_workload_outbound'].values

        labor_in_list, labor_out_list, amr_list = [], [], []
        for t in future_idx:
            if t in self.df.index:
                labor_in_list.append(self.df.loc[t, 'labor_inbound'])
                labor_out_list.append(self.df.loc[t, 'labor_outbound'])
                amr_list.append(self.df.loc[t, 'amr_active'])
            else:
                labor_in_list.append(3)
                labor_out_list.append(3)
                amr_list.append(4)

        df_plan['labor_inbound'] = labor_in_list
        df_plan['labor_outbound'] = labor_out_list
        df_plan['amr_active'] = amr_list

        # 3. Lấy tồn kho hiện tại (initial_stocks)
        if initial_stocks is None:
            if current_time in self.df.index:
                s_in = int(self.df.loc[current_time, 'storage_inbound'])
                s_buf = int(self.df.loc[current_time, 'storage_buffer'])
                s_out = int(self.df.loc[current_time, 'storage_outbound'])
            else:
                s_in, s_buf, s_out = 50.0, 100.0, 50.0
            initial_stocks = (s_in, s_buf, s_out)

        return df_plan, initial_stocks

    def get_control_room_data(self, current_time, horizon=1, lookback=5):
        """
        Hàm lấy dữ liệu chuẩn bị cho giao diện Control Room Streamlit:
        - history_df: 5 giờ quá khứ thực tế đến current_time
        - df_plan: Kế hoạch tương lai (workload dự báo, labor, amr)
        - init_stocks: Bộ tồn kho hiện tại (inbound, buffer, outbound)
        """
        # Đồng bộ hóa bias thực tế trước khi dự báo để bắt trọn Volume Spike
        self.sync_bias_up_to(current_time, warmup_hours=48)

        hist_start = current_time - pd.Timedelta(hours=lookback)
        history_df = self.df.loc[hist_start:current_time].copy()
        df_plan, init_stocks = self.get_plan_for_capacity_model(current_time, horizon=horizon)
        return history_df, df_plan, init_stocks

    def create_5_control_room_charts(self, history_df, sim_future, current_time, horizon=1, sim_after = None):
        """
        Tạo đối tượng Figure chứa trọn vẹn 5 biểu đồ dạng Cửa Sổ Trượt (Sliding Window):
        - Quá khứ (5h trước): Đường nét liền đen/màu đậm (Actual)
        - Tương lai (horizon giờ tới): Đường nét đứt màu (Predicted Workload / Simulated Storage)
        """
        fig, axes = plt.subplots(5, 1, figsize=(15, 18), sharex=False)

        # 1. Inbound Workload
        axes[0].plot(history_df.index, history_df['workload_inbound'], 'k-o', linewidth=2, label='Actual Quá khứ')
                        # Đường Xanh: Luôn giữ nguyên nhu cầu tự nhiên của ML
        axes[0].plot(sim_future.index, sim_future['workload_inbound'], color='tab:blue', linestyle='--', marker='s', linewidth=2, label=f'Dự báo Nhu cầu Tự nhiên ({horizon}h tới)')
        axes[0].plot([history_df.index[-1], sim_future.index[0]], [history_df['workload_inbound'].iloc[-1], sim_future['workload_inbound'].iloc[0]], color='tab:blue', linestyle=':')
                
                        # Đường Cam: Kế hoạch dỡ hàng thực tế sau khi đã thương lượng Heijunka (nếu có dời tải)
        if sim_after is not None and not sim_after['workload_inbound'].equals(sim_future['workload_inbound']):
            axes[0].plot(sim_after.index, sim_after['workload_inbound'], color='tab:orange', linestyle='--', marker='^', linewidth=2.5, label='Kế hoạch dỡ hàng sau Heijunka (Dời tải)')
            axes[0].plot([history_df.index[-1], sim_after.index[0]], [history_df['workload_inbound'].iloc[-1], sim_after['workload_inbound'].iloc[0]], color='tab:orange', linestyle=':')
                
        axes[0].axvline(x=current_time, color='gray', linestyle='--', linewidth=1.5)
        axes[0].set_title(f'BẢNG 1: DỰ BÁO WORKLOAD INBOUND — [5h Quá khứ + Dự báo {horizon}h tới]', fontsize=10, fontweight='bold')
        axes[0].set_ylabel('Pallets/h'); axes[0].legend(loc='upper left'); axes[0].grid(True, linestyle='--', alpha=0.5)
                
                        # 2. Outbound Workload
        axes[1].plot(history_df.index, history_df['workload_outbound'], 'k-o', linewidth=2, label='Actual Quá khứ')
        axes[1].plot(sim_future.index, sim_future['workload_outbound'], color='tab:green', linestyle='--', marker='s', linewidth=2, label=f'Dự báo Xuất Tự nhiên ({horizon}h tới)')
        axes[1].plot([history_df.index[-1], sim_future.index[0]], [history_df['workload_outbound'].iloc[-1], sim_future['workload_outbound'].iloc[0]], color='tab:green', linestyle=':')
                
        if sim_after is not None and not sim_after['workload_outbound'].equals(sim_future['workload_outbound']):
            axes[1].plot(sim_after.index, sim_after['workload_outbound'], color='tab:orange', linestyle='--', marker='^', linewidth=2.5, label='Kế hoạch bốc xe sau Heijunka')
            axes[1].plot([history_df.index[-1], sim_after.index[0]], [history_df['workload_outbound'].iloc[-1], sim_after['workload_outbound'].iloc[0]], color='tab:orange', linestyle=':')
                
        axes[1].axvline(x=current_time, color='gray', linestyle='--', linewidth=1.5)
        axes[1].set_title(f'BẢNG 2: DỰ BÁO WORKLOAD OUTBOUND — [5h Quá khứ + Dự báo {horizon}h tới]', fontsize=10, fontweight='bold')
        axes[1].set_ylabel('Pallets/h'); axes[1].legend(loc='upper left'); axes[1].grid(True, linestyle='--', alpha=0.5)

        # 3. Storage Inbound
        axes[2].plot(history_df.index, history_df['storage_inbound'], color='purple', marker='o', linewidth=2, label='Tồn kho Quá khứ')
        axes[2].plot(sim_future.index, sim_future['storage_inbound_sim'], color='tab:purple', linestyle='--', marker='s', linewidth=2, label=f'Mô phỏng {horizon}h tới')
        axes[2].plot([history_df.index[-1], sim_future.index[0]], [history_df['storage_inbound'].iloc[-1], sim_future['storage_inbound_sim'].iloc[0]], color='tab:purple', linestyle=':')
        axes[2].axhline(y=WARN_STORAGE_INBOUND, color='gold', linestyle='--', linewidth=1.5, label=f'Cảnh báo ({WARN_STORAGE_INBOUND:.0f})')
        axes[2].axhline(y=MAX_STORAGE_INBOUND, color='red', linestyle='-', linewidth=1.5, label=f'Nghẽn/Trần ({MAX_STORAGE_INBOUND})')
        axes[2].axvline(x=current_time, color='gray', linestyle='--', linewidth=1.5)
        axes[2].set_title(f'BẢNG 3: MÔ PHỎNG SÀN DỠ HÀNG INBOUND — [5h Quá khứ + Dự báo {horizon}h tới]', fontsize=10, fontweight='bold')
        axes[2].set_ylabel('Pallets'); axes[2].legend(loc='upper left'); axes[2].grid(True, linestyle='--', alpha=0.5)

        # 4. Storage Buffer
        axes[3].plot(history_df.index, history_df['storage_buffer'], color='darkorange', marker='o', linewidth=2, label='Tồn kho Quá khứ')
        axes[3].plot(sim_future.index, sim_future['storage_buffer_sim'], color='tab:orange', linestyle='--', marker='s', linewidth=2, label=f'Mô phỏng {horizon}h tới')
        axes[3].plot([history_df.index[-1], sim_future.index[0]], [history_df['storage_buffer'].iloc[-1], sim_future['storage_buffer_sim'].iloc[0]], color='tab:orange', linestyle=':')
        axes[3].axhline(y=WARN_STORAGE_BUFFER, color='gold', linestyle='--', linewidth=1.5, label=f'Cảnh báo ({WARN_STORAGE_BUFFER:.0f})')
        axes[3].axhline(y=MAX_STORAGE_BUFFER, color='red', linestyle='-', linewidth=1.5, label=f'Nghẽn/Trần ({MAX_STORAGE_BUFFER})')
        axes[3].axvline(x=current_time, color='gray', linestyle='--', linewidth=1.5)
        axes[3].set_title(f'BẢNG 4: MÔ PHỎNG KHO ĐỆM KITTING BUFFER — [5h Quá khứ + Dự báo {horizon}h tới]', fontsize=10, fontweight='bold')
        axes[3].set_ylabel('Khay/Thùng'); axes[3].legend(loc='upper left'); axes[3].grid(True, linestyle='--', alpha=0.5)

        # 5. Storage Outbound
        axes[4].plot(history_df.index, history_df['storage_outbound'], color='saddlebrown', marker='o', linewidth=2, label='Tồn kho Quá khứ')
        axes[4].plot(sim_future.index, sim_future['storage_outbound_sim'], color='tab:brown', linestyle='--', marker='s', linewidth=2, label=f'Mô phỏng {horizon}h tới')
        axes[4].plot([history_df.index[-1], sim_future.index[0]], [history_df['storage_outbound'].iloc[-1], sim_future['storage_outbound_sim'].iloc[0]], color='tab:brown', linestyle=':')
        axes[4].axhline(y=WARN_STORAGE_OUTBOUND, color='gold', linestyle='--', linewidth=1.5, label=f'Cảnh báo ({WARN_STORAGE_OUTBOUND:.0f})')
        axes[4].axhline(y=MAX_STORAGE_OUTBOUND, color='red', linestyle='-', linewidth=1.5, label=f'Nghẽn/Trần ({MAX_STORAGE_OUTBOUND})')
        axes[4].axvline(x=current_time, color='gray', linestyle='--', linewidth=1.5)
        axes[4].set_title(f'BẢNG 5: MÔ PHỎNG SÀN TẬP KẾT OUTBOUND — [5h Quá khứ + Dự báo {horizon}h tới]', fontsize=10, fontweight='bold')
        axes[4].set_ylabel('Pallets'); axes[4].set_xlabel('Thời gian'); axes[4].legend(loc='upper left'); axes[4].grid(True, linestyle='--', alpha=0.5)

        plt.tight_layout()
        return fig



#  CHẠY BATCH TOÀN BỘ 2027 (FILE GỐC: VẼ 5 BẢNG DASHBOARD & LƯU CSV)

if __name__ == "__main__":
    print("=" * 70)
    print("  DENSO LOGISTICS - INFERENCE FINAL (3 HORIZONS + CAPACITY COMPATIBLE)")
    print("=" * 70)

    data_path = resolve_path("denso_logistics_simulation_test.csv")
    df = pd.read_csv(data_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)
    df = df.asfreq('h')

    model_inbound = joblib.load(resolve_path('model_inbound.pkl'))
    model_outbound = joblib.load(resolve_path('model_outbound.pkl'))
    feature_cols_dict = joblib.load(resolve_path('model_features.pkl'))

    # Trích xuất đặc trưng cho toàn năm 2027
    feature_inbound = workload_lag_feature(df, 'workload_inbound')
    feature_outbound = workload_lag_feature(df, 'workload_outbound')

    test_in = feature_inbound.loc['2027'].dropna()
    test_out = feature_outbound.loc['2027'].dropna()
    common_idx = test_in.index.intersection(test_out.index)
    test_in = test_in.loc[common_idx]
    test_out = test_out.loc[common_idx]

    X_test_in = test_in[feature_cols_dict['workload_inbound']]
    y_test_in = test_in['target']
    X_test_out = test_out[feature_cols_dict['workload_outbound']]
    y_test_out = test_out['target']

    # 1. Dự báo 1h Real-time Adaptive (Chuẩn file gốc)
    pred_inbound = adaptive_prediction_in_real_time(model_inbound, X_test_in, y_test_in, alpha=0.35)
    pred_outbound = adaptive_prediction_in_real_time(model_outbound, X_test_out, y_test_out, alpha=0.35)

    mae_in = mean_absolute_error(y_test_in, pred_inbound)
    rmse_in = np.sqrt(mean_squared_error(y_test_in, pred_inbound))
    mae_out = mean_absolute_error(y_test_out, pred_outbound)
    rmse_out = np.sqrt(mean_squared_error(y_test_out, pred_outbound))

    print("\n[1/3] KẾT QUẢ DỰ BÁO NĂM 2027 (1h Real-time Adaptive):")
    print(f"  Workload INBOUND  -> MAE: {mae_in:.2f} | RMSE: {rmse_in:.2f}")
    print(f"  Workload OUTBOUND -> MAE: {mae_out:.2f} | RMSE: {rmse_out:.2f}")

    # 2. Mô phỏng dòng chảy 3 kho (Chuẩn 100% logic gốc)
    print("\n[2/3] Đang mô phỏng dòng chảy kho và xuất 5 bảng CSV...")
    df_2027 = df.loc[common_idx].copy()
    s_inbound = float(df.loc['2026', 'storage_inbound'].iloc[-1])
    s_buffer = float(df.loc['2026', 'storage_buffer'].iloc[-1])
    s_outbound = float(df.loc['2026', 'storage_outbound'].iloc[-1])

    simulating_storage_inbound = []
    simulating_storage_buffer = []
    simulating_storage_outbound = []
    capacity_in_list = []
    capacity_out_list = []

    SOFT_CAP_IN = MAX_STORAGE_INBOUND * 2.5
    SOFT_CAP_BUF = MAX_STORAGE_BUFFER * 2.5
    SOFT_CAP_OUT = MAX_STORAGE_OUTBOUND * 2.5

    for idx in common_idx:
        w_in = pred_inbound.loc[idx]
        w_out = pred_outbound.loc[idx]
        labor_in = df_2027.loc[idx, 'labor_inbound']
        labor_out = df_2027.loc[idx, 'labor_outbound']
        amr = df_2027.loc[idx, 'amr_active']
        hour = idx.hour

        # Kho 1: Kho Inbound
        capacity_in = labor_in * RATE_LABOR_INBOUND
        available_in = s_inbound + w_in
        space_in_buffer = max(0, MAX_STORAGE_BUFFER - s_buffer)
        flow_in = (min(available_in * 0.6, capacity_in, space_in_buffer))

        # Kho 2: Kho Buffer
        amr_capacity = amr * RATE_AMR
        target_out = MAX_STORAGE_OUTBOUND * 0.5
        if 20 <= hour or hour <= 5: target_out = MAX_STORAGE_OUTBOUND * 0.8
        elif hour in [6, 7]: target_out = MAX_STORAGE_OUTBOUND * 0.3

        amr_demand = max(0, w_out + (target_out - s_outbound) * 0.5)
        available_buffer = s_buffer + flow_in
        space_in_out = max(0, MAX_STORAGE_OUTBOUND - s_outbound)
        flow_out = min(amr_capacity, space_in_out, amr_demand, available_buffer * 0.7)

        # Kho 3: Kho Outbound
        capacity_out = labor_out * RATE_LABOR_OUTBOUND
        truck_demand = w_out
        available_out = s_outbound + flow_out
        ship_out = min(capacity_out, truck_demand, available_out)

        s_inbound = available_in - flow_in
        s_buffer = available_buffer - flow_out
        s_outbound = available_out - ship_out

        s_inbound = min(s_inbound, SOFT_CAP_IN)
        s_buffer = min(s_buffer, SOFT_CAP_BUF)
        s_outbound = min(s_outbound, SOFT_CAP_OUT)

        capacity_in_list.append(capacity_in)
        capacity_out_list.append(capacity_out)
        simulating_storage_inbound.append(s_inbound)
        simulating_storage_buffer.append(s_buffer)
        simulating_storage_outbound.append(s_outbound)

    # Xuất 5 Bảng CSV
    table_1_inbound = pd.DataFrame({
        'timestamp': common_idx,
        'actual_workload_inbound': y_test_in.values,
        'pred_workload_inbound': np.round(pred_inbound.values, 1),
        'labor_inbound': df_2027['labor_inbound'].values,
        'capacity_inbound': capacity_in_list,
        'scenario': df_2027['scenario'].values
    }).set_index('timestamp')

    table_2_outbound = pd.DataFrame({
        'timestamp': common_idx,
        'actual_workload_outbound': y_test_out.values,
        'pred_workload_outbound': np.round(pred_outbound.values, 1),
        'labor_outbound': df_2027['labor_outbound'].values,
        'amr_active': df_2027['amr_active'].values,
        'capacity_outbound': capacity_out_list,
        'scenario': df_2027['scenario'].values
    }).set_index('timestamp')

    table_3_storage_in = pd.DataFrame({
        'timestamp': common_idx,
        'storage_inbound_sim': np.round(simulating_storage_inbound, 1),
        'storage_inbound_actual': df_2027['storage_inbound'].values,
        'max_threshold': MAX_STORAGE_INBOUND,
        'is_bottleneck': [val >= MAX_STORAGE_INBOUND for val in simulating_storage_inbound],
        'scenario': df_2027['scenario'].values
    }).set_index('timestamp')

    table_4_storage_buf = pd.DataFrame({
        'timestamp': common_idx,
        'storage_buffer_sim': np.round(simulating_storage_buffer, 1),
        'storage_buffer_actual': df_2027['storage_buffer'].values,
        'max_threshold': MAX_STORAGE_BUFFER,
        'is_bottleneck': [val >= MAX_STORAGE_BUFFER for val in simulating_storage_buffer],
        'scenario': df_2027['scenario'].values
    }).set_index('timestamp')

    table_5_storage_out = pd.DataFrame({
        'timestamp': common_idx,
        'storage_outbound_sim': np.round(simulating_storage_outbound, 1),
        'storage_outbound_actual': df_2027['storage_outbound'].values,
        'max_threshold': MAX_STORAGE_OUTBOUND,
        'is_bottleneck': [val >= MAX_STORAGE_OUTBOUND for val in simulating_storage_outbound],
        'scenario': df_2027['scenario'].values
    }).set_index('timestamp')

    table_1_inbound.to_csv("table_1_workload_inbound.csv")
    table_2_outbound.to_csv("table_2_workload_outbound.csv")
    table_3_storage_in.to_csv("table_3_storage_inbound.csv")
    table_4_storage_buf.to_csv("table_4_storage_buffer.csv")
    table_5_storage_out.to_csv("table_5_storage_outbound.csv")
    print("  -> Đã lưu 5 bảng: table_1_... đến table_5_... thành công.")

    # Vẽ và lưu biểu đồ 5 Panel tổng quan
    fig, axes = plt.subplots(5, 1, figsize=(16, 18), sharex=True)
    axes[0].plot(table_1_inbound.index, table_1_inbound['actual_workload_inbound'], label='Actual Inbound', color='black', alpha=0.5)
    axes[0].plot(table_1_inbound.index, table_1_inbound['pred_workload_inbound'], label='Predicted Inbound (HistXGB)', color='tab:blue', linewidth=1.2)
    axes[0].set_title('BẢNG 1: DỰ BÁO WORKLOAD INBOUND (NHẬP HÀNG TẠI DOCK)', fontsize=10, fontweight='bold')
    axes[0].set_ylabel('Pallets/h'); axes[0].legend(loc='upper left'); axes[0].grid(True, linestyle='--', alpha=0.5)

    axes[1].plot(table_2_outbound.index, table_2_outbound['actual_workload_outbound'], label='Actual Outbound', color='black', alpha=0.5)
    axes[1].plot(table_2_outbound.index, table_2_outbound['pred_workload_outbound'], label='Predicted Outbound (HistXGB)', color='tab:green', linewidth=1.2)
    axes[1].set_title('BẢNG 2: DỰ BÁO WORKLOAD OUTBOUND (XUẤT HÀNG RA XE)', fontsize=10, fontweight='bold')
    axes[1].set_ylabel('Pallets/h'); axes[1].legend(loc='upper left'); axes[1].grid(True, linestyle='--', alpha=0.5)

    axes[2].plot(table_3_storage_in.index, table_3_storage_in['storage_inbound_sim'], label='Simulated Storage Inbound', color='tab:purple', linewidth=1.2)
    axes[2].axhline(y=WARN_STORAGE_INBOUND, color='gold', linestyle='--', linewidth=1.5, label=f'Cảnh báo ({WARN_STORAGE_INBOUND})')
    axes[2].axhline(y=MAX_STORAGE_INBOUND, color='red', linestyle='-', linewidth=1.5, label=f'Nghẽn/Trần ({MAX_STORAGE_INBOUND})')
    axes[2].fill_between(table_3_storage_in.index, MAX_STORAGE_INBOUND, table_3_storage_in['storage_inbound_sim'], 
                         where=(table_3_storage_in['storage_inbound_sim'] >= MAX_STORAGE_INBOUND), color='red', alpha=0.3)
    axes[2].fill_between(table_3_storage_in.index, WARN_STORAGE_INBOUND, table_3_storage_in['storage_inbound_sim'], 
                         where=(table_3_storage_in['storage_inbound_sim'] >= WARN_STORAGE_INBOUND) & (table_3_storage_in['storage_inbound_sim'] < MAX_STORAGE_INBOUND), color='gold', alpha=0.3)
    axes[2].set_title('BẢNG 3: MÔ PHỎNG SÀN DỠ HÀNG INBOUND', fontsize=10, fontweight='bold')
    axes[2].set_ylabel('Pallets'); axes[2].legend(loc='upper left'); axes[2].grid(True, linestyle='--', alpha=0.5)

    axes[3].plot(table_4_storage_buf.index, table_4_storage_buf['storage_buffer_sim'], label='Simulated Storage Buffer', color='tab:orange', linewidth=1.2)
    axes[3].axhline(y=WARN_STORAGE_BUFFER, color='gold', linestyle='--', linewidth=1.5, label=f'Cảnh báo ({WARN_STORAGE_BUFFER})')
    axes[3].axhline(y=MAX_STORAGE_BUFFER, color='red', linestyle='-', linewidth=1.5, label=f'Nghẽn/Trần ({MAX_STORAGE_BUFFER})')
    axes[3].fill_between(table_4_storage_buf.index, MAX_STORAGE_BUFFER, table_4_storage_buf['storage_buffer_sim'], 
                         where=(table_4_storage_buf['storage_buffer_sim'] >= MAX_STORAGE_BUFFER), color='red', alpha=0.3)
    axes[3].fill_between(table_4_storage_buf.index, WARN_STORAGE_BUFFER, table_4_storage_buf['storage_buffer_sim'], 
                         where=(table_4_storage_buf['storage_buffer_sim'] >= WARN_STORAGE_BUFFER) & (table_4_storage_buf['storage_buffer_sim'] < MAX_STORAGE_BUFFER), color='gold', alpha=0.3)
    axes[3].set_title('BẢNG 4: MÔ PHỎNG KHO ĐỆM KITTING BUFFER', fontsize=10, fontweight='bold')
    axes[3].set_ylabel('Khay/Thùng'); axes[3].legend(loc='upper left'); axes[3].grid(True, linestyle='--', alpha=0.5)

    axes[4].plot(table_5_storage_out.index, table_5_storage_out['storage_outbound_sim'], label='Simulated Storage Outbound', color='tab:brown', linewidth=1.2)
    axes[4].axhline(y=WARN_STORAGE_OUTBOUND, color='gold', linestyle='--', linewidth=1.5, label=f'Cảnh báo ({WARN_STORAGE_OUTBOUND})')
    axes[4].axhline(y=MAX_STORAGE_OUTBOUND, color='red', linestyle='-', linewidth=1.5, label=f'Nghẽn/Trần ({MAX_STORAGE_OUTBOUND})')
    axes[4].fill_between(table_5_storage_out.index, MAX_STORAGE_OUTBOUND, table_5_storage_out['storage_outbound_sim'], 
                         where=(table_5_storage_out['storage_outbound_sim'] >= MAX_STORAGE_OUTBOUND), color='red', alpha=0.3)
    axes[4].fill_between(table_5_storage_out.index, WARN_STORAGE_OUTBOUND, table_5_storage_out['storage_outbound_sim'], 
                         where=(table_5_storage_out['storage_outbound_sim'] >= WARN_STORAGE_OUTBOUND) & (table_5_storage_out['storage_outbound_sim'] < MAX_STORAGE_OUTBOUND), color='gold', alpha=0.3)
    axes[4].set_title('BẢNG 5: MÔ PHỎNG SÀN TẬP KẾT OUTBOUND', fontsize=10, fontweight='bold')
    axes[4].set_ylabel('Pallets'); axes[4].set_xlabel('Thời gian (Q1/2027)'); axes[4].legend(loc='upper left'); axes[4].grid(True, linestyle='--', alpha=0.5)
    plt.tight_layout()
    plt.savefig("denso_logistics_5_tables_dashboard.png", dpi=150)
    print("  -> Đã lưu biểu đồ tổng thể: denso_logistics_5_tables_dashboard.png")


    # TEST KẾT NỐI VỚI CAPACITY_MODEL.PY (BẢO ĐẢM TƯƠNG THÍCH 100%)

    print("\n[3/3] KIỂM THỬ KẾT NỐI TRỰC TIẾP VỚI CAPACITY_MODEL.PY...")
    try:
        from capacity_model import CapacityModelEngine
        
        forecaster = WarehouseForecaster()
        sample_time = pd.Timestamp("2027-01-05 05:00")
        
        # 1. Lấy plan từ forecaster
        df_plan, init_stocks = forecaster.get_plan_for_capacity_model(sample_time, horizon=12)
        print(f"  1. Tạo df_plan 12h thành công! Cột: {list(df_plan.columns)}")
        print(f"     Initial stocks tại {sample_time.strftime('%H:%M %d/%m')}: In={init_stocks[0]}, Buf={init_stocks[1]}, Out={init_stocks[2]}")
        
        # 2. Đưa thẳng vào CapacityModelEngine giải quyết bottleneck
        cap_engine = CapacityModelEngine()
        solution = cap_engine.solve_capacity_bottleneck(df_plan, init_stocks)
        print(f"  2. Phản hồi từ CapacityModelEngine: [{solution['status']}]")
        if solution['status'] == 'SUCCESS':
            print(f"     -> Giải pháp đề xuất: {solution['level']}")
            for log in solution['action_logs']:
                print(f"     * {log}")
        else:
            print(f"     -> {solution.get('message', 'Vận hành ổn định.')}")
        print("  -> KẾT NỐI CAPACITY_MODEL HOÀN TOÀN THÀNH CÔNG!")
    except Exception as e:
        print(f"  Lỗi khi gọi capacity_model: {e}")
