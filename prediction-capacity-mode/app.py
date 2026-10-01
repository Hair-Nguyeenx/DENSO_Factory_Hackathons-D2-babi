import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ==============================================================================
# 1. KẾT NỐI VỚI 2 ENGINE: DỰ BÁO (INFERENCE) VÀ ĐIỀU ĐỘ (CAPACITY MODEL)
# ==============================================================================
from inference_final import (
    WarehouseForecaster,
    WARN_STORAGE_INBOUND, MAX_STORAGE_INBOUND,
    WARN_STORAGE_BUFFER, MAX_STORAGE_BUFFER,
    WARN_STORAGE_OUTBOUND, MAX_STORAGE_OUTBOUND
)
from capacity_model import CapacityModelEngine

st.set_page_config(
    page_title="Denso Logistics Control Room", 
    page_icon="🏭",
    layout="wide"
)

st.title("🏭 DENSO LOGISTICS - INTELLIGENT CONTROL ROOM")
st.markdown("Hệ thống Giám sát & Điều độ Chủ động Dòng chảy Kho 3 Tầng (Closed-loop Rolling Control)")

# Khởi tạo Engine (cache để tối ưu hiệu năng không load lại model)
@st.cache_resource
def load_engines():
    forecaster = WarehouseForecaster(data_path="denso_logistics_simulation_test.csv")
    capacity_engine = CapacityModelEngine()
    return forecaster, capacity_engine

forecaster, capacity_engine = load_engines()


def plot_3_storage_preview(df_before, df_after, horizon):
    """
    Vẽ 3 biểu đồ tồn kho đối chiếu [Trước khi can thiệp] vs [Sau khi can thiệp]
    để người vận hành kiểm tra trực quan trước khi bấm nút áp dụng vào hệ thống.
    """
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    idx = df_before.index
    
    # 1. Sàn Dỡ Hàng Inbound
    axes[0].plot(idx, df_before['storage_inbound_sim'], color='tab:red', linestyle='--', marker='o', linewidth=1.8, label='Trước can thiệp (Chưa sửa)')
    axes[0].plot(idx, df_after['storage_inbound_sim'], color='tab:purple', linestyle='-', marker='s', linewidth=2.2, label='Sau can thiệp (Đã sửa)')
    axes[0].axhline(WARN_STORAGE_INBOUND, color='gold', linestyle='--', linewidth=1.5, label=f'Cảnh báo ({WARN_STORAGE_INBOUND:.0f})')
    axes[0].axhline(MAX_STORAGE_INBOUND, color='red', linestyle='-', linewidth=1.5, label=f'Nghẽn/Trần ({MAX_STORAGE_INBOUND:.0f})')
    axes[0].set_ylabel('Pallets')
    axes[0].set_title('1. Mô phỏng Sàn Dỡ Hàng Inbound', fontsize=11, fontweight='bold')
    axes[0].legend(loc='upper left', fontsize=9)
    axes[0].grid(True, linestyle='--', alpha=0.5)

    # 2. Kho Đệm Kitting Buffer
    axes[1].plot(idx, df_before['storage_buffer_sim'], color='tab:red', linestyle='--', marker='o', linewidth=1.8, label='Trước can thiệp (Chưa sửa)')
    axes[1].plot(idx, df_after['storage_buffer_sim'], color='tab:orange', linestyle='-', marker='s', linewidth=2.2, label='Sau can thiệp (Đã sửa)')
    axes[1].axhline(WARN_STORAGE_BUFFER, color='gold', linestyle='--', linewidth=1.5, label=f'Cảnh báo ({WARN_STORAGE_BUFFER:.0f})')
    axes[1].axhline(MAX_STORAGE_BUFFER, color='red', linestyle='-', linewidth=1.5, label=f'Nghẽn/Trần ({MAX_STORAGE_BUFFER:.0f})')
    axes[1].set_ylabel('Khay/Thùng')
    axes[1].set_title('2. Mô phỏng Kho Đệm Kitting Buffer', fontsize=11, fontweight='bold')
    axes[1].legend(loc='upper left', fontsize=9)
    axes[1].grid(True, linestyle='--', alpha=0.5)

    # 3. Sàn Tập Kết Outbound
    axes[2].plot(idx, df_before['storage_outbound_sim'], color='tab:red', linestyle='--', marker='o', linewidth=1.8, label='Trước can thiệp (Chưa sửa)')
    axes[2].plot(idx, df_after['storage_outbound_sim'], color='tab:brown', linestyle='-', marker='s', linewidth=2.2, label='Sau can thiệp (Đã sửa)')
    axes[2].axhline(WARN_STORAGE_OUTBOUND, color='gold', linestyle='--', linewidth=1.5, label=f'Cảnh báo ({WARN_STORAGE_OUTBOUND:.0f})')
    axes[2].axhline(MAX_STORAGE_OUTBOUND, color='red', linestyle='-', linewidth=1.5, label=f'Nghẽn/Trần ({MAX_STORAGE_OUTBOUND:.0f})')
    axes[2].set_ylabel('Pallets')
    axes[2].set_title('3. Mô phỏng Sàn Tập Kết Outbound', fontsize=11, fontweight='bold')
    axes[2].legend(loc='upper left', fontsize=9)
    axes[2].grid(True, linestyle='--', alpha=0.5)

    plt.tight_layout()
    return fig


# ==============================================================================
# QUẢN LÝ BỘ NHỚ TRẠNG THÁI LIÊN TỤC (SESSION STATE)
# ==============================================================================
if 'current_time' not in st.session_state:
    st.session_state['current_time'] = pd.Timestamp("2027-01-05 05:00")

# Bộ nhớ cam kết dời tải Heijunka (lưu {timestamp: delta_pallets})
if 'committed_heijunka_in' not in st.session_state:
    st.session_state['committed_heijunka_in'] = {}

if 'committed_heijunka_out' not in st.session_state:
    st.session_state['committed_heijunka_out'] = {}

# Tồn kho mô phỏng thực tế kế thừa từ các ca trước (Inbound, Buffer, Outbound)
if 'simulated_stocks' not in st.session_state:
    st.session_state['simulated_stocks'] = None

# Trạng thái duy trì áp dụng kịch bản điều độ
if 'plan_applied' not in st.session_state:
    st.session_state['plan_applied'] = False

# Trạng thái mở hộp thoại/tab xem chi tiết giải pháp gợi ý
if 'show_solution_panel' not in st.session_state:
    st.session_state['show_solution_panel'] = False

# ==============================================================================
# 2. SIDEBAR: LỰA CHỌN KHUNG GIỜ VÀ ĐIỀU KHIỂN ĐỒNG HỒ MÔ PHỎNG
# ==============================================================================
st.sidebar.header("🕹️ BẢNG ĐIỀU KHIỂN")

horizon_choice = st.sidebar.radio(
    "⏱️ Chọn Khung Giờ Dự Báo (Horizon):",
    options=[1, 3, 12, 24],
    format_func=lambda x: f"Dự báo {x} giờ tới",
    index=1  # Mặc định chọn 3h
)

st.sidebar.markdown("---")
st.sidebar.subheader("⏰ Đồng Hồ Vận Hành")
curr_t = st.session_state['current_time']
st.sidebar.info(f"Thời điểm hiện tại:\n### {curr_t.strftime('%H:%M - %d/%m/%Y')}")

# Nút bước sang 1 giờ tiếp theo (+1h)
if st.sidebar.button("⏭️ Bước sang 1 giờ tiếp theo (+1h)", use_container_width=True):
    # 1. Bóc tách lượng Heijunka đã hẹn trước đó khi cập nhật sai số cho ML
    delta_in_done = st.session_state['committed_heijunka_in'].get(curr_t, 0.0)
    delta_out_done = st.session_state['committed_heijunka_out'].get(curr_t, 0.0)
    forecaster.update_actual_at_hour(curr_t, intervention_delta_in=delta_in_done, intervention_delta_out=delta_out_done)

    # 2. Chuyển giao tồn kho mô phỏng: Lấy kết quả cuối giờ vừa chạy làm đầu giờ ca sau
    if 'effective_sim' in st.session_state and st.session_state['effective_sim'] is not None:
        eff_df = st.session_state['effective_sim']
        next_t = curr_t + pd.Timedelta(hours=1)
        if next_t in eff_df.index:
            st.session_state['simulated_stocks'] = (
                float(eff_df.loc[next_t, 'storage_inbound_sim']),
                float(eff_df.loc[next_t, 'storage_buffer_sim']),
                float(eff_df.loc[next_t, 'storage_outbound_sim'])
            )

    st.session_state['current_time'] += pd.Timedelta(hours=1)
    st.session_state['show_solution_panel'] = False
    st.session_state['plan_applied'] = False  # Đặt lại trạng thái để sẵn sàng quét nghẽn cho mốc giờ mới
    st.rerun()

col_b1, col_b2 = st.sidebar.columns(2)
with col_b1:
    if st.sidebar.button("⏩ +6 Giờ", use_container_width=True):
        st.session_state['current_time'] += pd.Timedelta(hours=6)
        st.session_state['show_solution_panel'] = False
        st.session_state['plan_applied'] = False  # Đặt lại trạng thái để sẵn sàng quét nghẽn cho mốc giờ mới
        st.rerun()
with col_b2:
    if st.sidebar.button("🔄 Reset về 05:00", use_container_width=True):
        st.session_state['current_time'] = pd.Timestamp("2027-01-05 05:00")
        st.session_state['committed_heijunka_in'] = {}
        st.session_state['committed_heijunka_out'] = {}
        st.session_state['simulated_stocks'] = None
        st.session_state['plan_applied'] = False
        st.session_state['effective_sim'] = None
        st.session_state['show_solution_panel'] = False
        st.rerun()

# ==============================================================================
# 3. KẾT NỐI DỮ LIỆU: INFERENCE -> CAPACITY MODEL
# ==============================================================================
current_time = st.session_state['current_time']

# BƯỚC 1: Lấy 5h quá khứ + Kế hoạch tương lai theo đúng horizon đã chọn
history_df, df_plan_natural, init_stocks_csv = forecaster.get_control_room_data(
    current_time, horizon=horizon_choice, lookback=5
)

# Tồn kho khởi điểm: Kế thừa từ ca mô phỏng trước, nếu chưa có thì lấy từ CSV
init_stocks = st.session_state['simulated_stocks'] if st.session_state['simulated_stocks'] is not None else init_stocks_csv

# BƯỚC 2: Tạo Kế hoạch Cam kết Heijunka (Đường Cam)
df_scheduled = df_plan_natural.copy()
has_active_heijunka = False

for t in df_scheduled.index:
    d_in = st.session_state['committed_heijunka_in'].get(t, 0.0)
    d_out = st.session_state['committed_heijunka_out'].get(t, 0.0)
    if d_in != 0.0 or d_out != 0.0:
        has_active_heijunka = True
        df_scheduled.loc[t, 'workload_inbound'] = max(0.0, df_scheduled.loc[t, 'workload_inbound'] + d_in)
        df_scheduled.loc[t, 'workload_outbound'] = max(0.0, df_scheduled.loc[t, 'workload_outbound'] + d_out)

# Mô phỏng dòng chảy kho cơ sở (chạy trên kế hoạch tự nhiên và kế hoạch cam kết)
sim_baseline = capacity_engine.simulate_24h(df_plan_natural, init_stocks)
sim_scheduled = capacity_engine.simulate_24h(df_scheduled, init_stocks)

# BƯỚC 3: Quét tìm bottleneck và tìm giải pháp tiếp ứng
try:
    solution = capacity_engine.solve_capacity_bottleneck(df_scheduled, init_stocks)
except Exception as e:
    solution = {
        'status': 'ERROR',
        'message': f"Lỗi trong capacity_model: {e}",
        'df_before': sim_scheduled,
        'df_after': sim_scheduled
    }

# ==============================================================================
# 4. GIAO DIỆN HIỂN THỊ TRÊN CONTROL ROOM
# ==============================================================================

# HÀNG 1: CÁC THẺ CHỈ SỐ NHANH
m1, m2, m3, m4, m5 = st.columns(5)
with m1:
    st.metric("Workload Inbound", f"{history_df['workload_inbound'].iloc[-1]:.0f} p/h")
with m2:
    st.metric("Workload Outbound", f"{history_df['workload_outbound'].iloc[-1]:.0f} p/h")
with m3:
    st.metric("Kho Inbound Dock", f"{init_stocks[0]:.0f} / 200", 
              delta=f"{init_stocks[0]-160:.0f}" if init_stocks[0]>160 else "An toàn", delta_color="inverse")
with m4:
    st.metric("Kho Kitting Buffer", f"{init_stocks[1]:.0f} / 500", 
              delta=f"{init_stocks[1]-400:.0f}" if init_stocks[1]>400 else "An toàn", delta_color="inverse")
with m5:
    st.metric("Sàn Tập Kết Outbound", f"{init_stocks[2]:.0f} / 300", 
              delta=f"{init_stocks[2]-240:.0f}" if init_stocks[2]>240 else "An toàn", delta_color="inverse")

st.markdown("---")

# HÀNG 2: HỘP ĐIỀU ĐỘ CHỦ ĐỘNG & QUYẾT ĐỊNH CAN THIỆP
st.subheader("💡 ĐIỀU ĐỘ CHỦ ĐỘNG & QUYẾT ĐỊNH CAN THIỆP")

effective_sim = None

if st.session_state['plan_applied']:
    # =========================================================================
    # TRƯỜNG HỢP A: KỊCH BẢN ĐÃ ĐƯỢC ÁP DỤNG THÀNH CÔNG
    # Ô CẢNH BÁO HOÀN TOÀN MẤT ĐI! THAY BẰNG THÔNG BÁO VẬN HÀNH XANH LÁ
    # =========================================================================
    st.success(f"✅ **ĐANG VẬN HÀNH THEO KẾ HOẠCH ĐIỀU ĐỘ (ĐƯỜNG MÀU CAM)** — Các nguy cơ nghẽn kho trong {horizon_choice}h tới đã được giải tỏa triệt để!")
    
    col_st1, col_st2 = st.columns([4, 1])
    with col_st1:
        st.info("ℹ️ Kế hoạch dời tải (Heijunka kéo sớm), điều động nhân lực và tăng ca OT đang được áp dụng trực tiếp lên dòng chảy kho bên dưới.")
    with col_st2:
        if st.button("↩️ Hủy áp dụng (Quay về tự nhiên)", use_container_width=True):
            if 'prev_committed_in' in st.session_state:
                st.session_state['committed_heijunka_in'] = dict(st.session_state['prev_committed_in'])
            if 'prev_committed_out' in st.session_state:
                st.session_state['committed_heijunka_out'] = dict(st.session_state['prev_committed_out'])
            st.session_state['plan_applied'] = False
            st.session_state['effective_sim'] = sim_baseline
            st.session_state['show_solution_panel'] = False
            st.rerun()

    effective_sim = st.session_state.get('effective_sim', sim_scheduled)

elif solution['status'] in ['SUCCESS', 'PARTIAL_SUCCESS']:
    # =========================================================================
    # TRƯỜNG HỢP B: PHÁT HIỆN NGHẼN KHO NHƯNG CHƯA ÁP DỤNG
    # =========================================================================
    # 1. Chỉ hiện ô cảnh báo ngắn gọn kèm nút hình chữ nhật rõ ràng
    st.warning(f"🚨 **CẢNH BÁO NGHẼN KHO:** Phát hiện nguy cơ vượt trần sức chứa trong {horizon_choice}h tới!")
    
    if not st.session_state['show_solution_panel']:
        if st.button("🔍 Bấm vào để xem giải pháp gợi ý của hệ thống", type="primary", use_container_width=True):
            st.session_state['show_solution_panel'] = True
            st.rerun()

    # 2. Khi bấm vào -> Mở ra khung/tab chi tiết giải pháp + 3 chart đối chiếu + 2 nút lựa chọn
    if st.session_state['show_solution_panel']:
        with st.container(border=True):
            st.markdown("### 📋 GIẢI PHÁP GỢI Ý CỦA HỆ THỐNG")
            
            col_s1, col_s2, col_s3 = st.columns(3)
            with col_s1:
                st.metric("Giảm Áp Lực Nghẽn", f"{solution.get('penalty_reduction_pct', 100):.1f}%")
            with col_s2:
                st.metric("Chi Phí Công OT", f"${solution.get('cost', 0):.1f}")
            with col_s3:
                st.metric("Số Giờ Nghẽn Còn Lại", f"{len(solution.get('remaining_bottlenecks', []))} mốc giờ")
                
            st.markdown(f"**Chiến lược tối ưu:** `{solution['level']}`")
            st.info(f"💬 **Thông điệp điều phối:** {solution.get('message', '')}")
            
            st.write("📋 **Chuỗi hành động phối hợp hệ thống đề xuất Quản đốc:**")
            for act in solution.get('action_logs', []):
                st.write(f"- {act}")
                
            rem_bns = solution.get('remaining_bottlenecks', [])
            if rem_bns:
                st.warning(f"⚠️ **Lưu ý các mốc giờ còn tồn nhẹ sau can thiệp:** " + 
                           ", ".join([f"{rb['hour']} ({rb['type']} +{rb['severity']:.1f})" for rb in rem_bns]))

            # VẼ 3 CHART KHO ĐỐI CHIẾU: TRƯỚC VS SAU KHI SỬA
            st.markdown("---")
            st.markdown("#### 📊 ĐỐI CHIẾU MÔ PHỎNG 3 KHO: [Trước khi sửa] vs [Sau khi sửa]")
            fig_preview = plot_3_storage_preview(sim_scheduled, solution['df_after'], horizon_choice)
            st.pyplot(fig_preview)
            
            # 2 Ô LỰA CHỌN CÓ MUỐN THAY ĐỔI KHÔNG
            st.markdown("---")
            st.markdown("#### 👉 Bạn có muốn áp dụng kịch bản điều độ này vào vận hành?")
            c_yes, c_no = st.columns(2)
            with c_yes:
                if st.button("✅ CÓ, ÁP DỤNG GIẢI PHÁP (Kích hoạt đường màu cam)", type="primary", use_container_width=True):
                    st.session_state['prev_committed_in'] = dict(st.session_state['committed_heijunka_in'])
                    st.session_state['prev_committed_out'] = dict(st.session_state['committed_heijunka_out'])
                    st.session_state['plan_applied'] = True
                    st.session_state['show_solution_panel'] = False
                    
                    # Ghi nhận các cam kết Heijunka mới phát sinh từ solution['df_after'] vào bộ nhớ dài hạn
                    for t in df_scheduled.index:
                        new_d_in = float(solution['df_after'].loc[t, 'workload_inbound']) - float(df_scheduled.loc[t, 'workload_inbound'])
                        new_d_out = float(solution['df_after'].loc[t, 'workload_outbound']) - float(df_scheduled.loc[t, 'workload_outbound'])
                        if new_d_in != 0.0:
                            st.session_state['committed_heijunka_in'][t] = st.session_state['committed_heijunka_in'].get(t, 0.0) + new_d_in
                        if new_d_out != 0.0:
                            st.session_state['committed_heijunka_out'][t] = st.session_state['committed_heijunka_out'].get(t, 0.0) + new_d_out

                    # Ghi nhận trực tiếp kết quả điều độ tối ưu từ solution làm kế hoạch thực thi chính
                    st.session_state['effective_sim'] = solution['df_after'].copy()
                    st.rerun()

            with c_no:
                if st.button("❌ KHÔNG, GIỮ NGUYÊN TRẠNG THÁI HIỆN TẠI", use_container_width=True):
                    st.session_state['show_solution_panel'] = False
                    st.rerun()

    # Chưa áp dụng thì biểu đồ chính vẫn giữ nguyên tự nhiên
    effective_sim = sim_scheduled if has_active_heijunka else None

elif solution['status'] == 'ERROR':
    effective_sim = None
    st.warning(f"⚠️ {solution['message']}")
else:
    # Vận hành an toàn, không có bottleneck
    if has_active_heijunka:
        effective_sim = sim_scheduled
        st.info("ℹ️ Không phát sinh nghẽn mới. Kho tiếp tục vận hành theo KẾ HOẠCH DỜI TẢI (ĐƯỜNG MÀU CAM) đã cam kết trước đó.")
    else:
        effective_sim = None
        st.session_state['effective_sim'] = sim_baseline
        st.success(f"✅ **HỆ THỐNG VẬN HÀNH AN TOÀN:** {solution.get('message', 'Không phát hiện điểm nghẽn.')}")

st.markdown("---")

# HÀNG 3: HIỂN THỊ TRỌN VẸN 5 BIỂU ĐỒ THEO KHUNG GIỜ ĐÃ CHỌN
st.subheader(f"📊 5 BIỂU ĐỒ GIÁM SÁT TOÀN DIỆN (Cửa sổ trượt: 5h quá khứ + {horizon_choice}h tương lai)")

fig = forecaster.create_5_control_room_charts(
    history_df=history_df, 
    sim_future=sim_baseline, 
    current_time=current_time, 
    horizon=horizon_choice, 
    sim_after=effective_sim
)
st.pyplot(fig)
