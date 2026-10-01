import os
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt

# Thiết lập đường dẫn thư mục gốc và thư mục prediction-capacity-mode
BASE_DIR = Path(__file__).resolve().parent.parent
PRED_DIR = BASE_DIR / "prediction-capacity-mode"
DATA_PATH = BASE_DIR / "denso_logistics_simulation_test.csv"

# Thêm PRED_DIR vào sys.path và chuyển working dir tạm thời để load đúng file pkl
sys.path.insert(0, str(PRED_DIR))
cwd_backup = os.getcwd()
try:
    os.chdir(str(PRED_DIR))
    from inference_final import (
        WarehouseForecaster,
        MAX_STORAGE_INBOUND,
        MAX_STORAGE_BUFFER,
        MAX_STORAGE_OUTBOUND,
        WARN_STORAGE_INBOUND,
        WARN_STORAGE_BUFFER,
        WARN_STORAGE_OUTBOUND,
        RATE_LABOR_INBOUND,
        RATE_LABOR_OUTBOUND,
        RATE_AMR,
    )
    from capacity_model import CapacityModelEngine
finally:
    os.chdir(cwd_backup)

# Cấu hình giao diện Streamlit
st.set_page_config(
    page_title="DENSO Factory Logistics - Control Room",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS: Ẩn mũi tên stMetricDelta, giữ nguyên màu sắc badge; tinh chỉnh card và legend
st.markdown("""
<style>
/* Ẩn dấu mũi tên trong stMetricDelta, giữ nguyên màu sắc badge */
[data-testid="stMetricDelta"] svg {
    display: none !important;
}

/* Thanh chú thích màu sắc tinh giản, chuyên nghiệp */
.status-legend-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 20px;
    font-size: 13px;
    margin-top: 4px;
    margin-bottom: 14px;
    padding: 8px 14px;
    background: rgba(255, 255, 255, 0.04);
    border-radius: 6px;
    border: 1px solid rgba(255, 255, 255, 0.08);
}
.legend-item {
    display: inline-flex;
    align-items: center;
    gap: 7px;
}
.legend-dot-green {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background-color: #09ab3b;
    display: inline-block;
}
.legend-dot-red {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background-color: #ff4b4b;
    display: inline-block;
}

/* Banner thông báo Preview Mode */
.preview-alert-banner {
    padding: 12px 18px;
    background: linear-gradient(90deg, rgba(230, 126, 34, 0.2) 0%, rgba(243, 156, 18, 0.15) 100%);
    border-left: 5px solid #e67e22;
    border-radius: 6px;
    margin-bottom: 18px;
    color: #f39c12;
}
</style>
""", unsafe_allow_html=True)

# Khởi tạo và cache mô hình dự báo
@st.cache_resource
def load_forecaster_engine():
    os.chdir(str(PRED_DIR))
    try:
        forecaster = WarehouseForecaster(data_path=str(DATA_PATH))
    finally:
        os.chdir(cwd_backup)
    engine = CapacityModelEngine()
    return forecaster, engine

forecaster, capacity_engine = load_forecaster_engine()

# Quản lý trạng thái Preview Mode trong Session State
if "preview_mode" not in st.session_state:
    st.session_state.preview_mode = False

# ==============================================================================
# THANH ĐIỀU KHIỂN (SIDEBAR)
# ==============================================================================
st.sidebar.markdown("### BỘ ĐIỀU KHIỂN TRUNG TÂM")

# Danh sách mốc thời gian khả dụng (năm 2027)
df_data = forecaster.df
timestamps_2027 = df_data.loc['2027'].index

default_time = pd.Timestamp("2027-01-05 08:00")
if default_time not in timestamps_2027:
    default_time = timestamps_2027[0]

selected_date = st.sidebar.date_input(
    "Chọn ngày vận hành",
    value=default_time.date(),
    min_value=timestamps_2027[0].date(),
    max_value=timestamps_2027[-1].date()
)

selected_hour = st.sidebar.slider(
    "Chọn giờ vận hành",
    min_value=0,
    max_value=23,
    value=int(default_time.hour),
    step=1,
    format="%02d:00"
)

current_time = pd.Timestamp(f"{selected_date} {selected_hour:02d}:00:00")

st.sidebar.markdown("---")
# Tùy chọn khoảng thời gian t (1h, 3h, 12h)
horizon_option = st.sidebar.radio(
    "Chọn khoảng thời gian dự báo (t)",
    options=["1h", "3h", "12h"],
    index=1,
    help="Hệ thống chỉ hiển thị duy nhất 1 bộ bảng cho khoảng thời gian t được chọn."
)
horizon_val = int(horizon_option.replace("h", ""))

st.sidebar.markdown("---")
show_charts = st.sidebar.checkbox("Hiển thị biểu đồ trực quan", value=True)
run_capacity_solve = st.sidebar.checkbox("Phân tích điều độ giải phóng nghẽn", value=True)

# ==============================================================================
# TÍNH TOÁN DỰ BÁO VÀ GIẢI PHÁP ĐIỀU ĐỘ
# ==============================================================================
history_df, df_plan, init_stocks = forecaster.get_control_room_data(
    current_time=current_time,
    horizon=horizon_val,
    lookback=5
)

# Chạy mô phỏng vật lý dòng chảy kho gốc
df_sim_original = capacity_engine.simulate_24h(df_plan, init_stocks)

# Chạy giải pháp điều độ từ CapacityModelEngine
plan_solution = capacity_engine.solve_capacity_bottleneck(df_plan, init_stocks)
solution_status = plan_solution.get("status", "NO_ACTION_NEEDED")
df_after_sol = plan_solution.get("df_after", df_sim_original)

# Dữ liệu hiển thị phụ thuộc vào chế độ Preview
is_preview = st.session_state.preview_mode and (solution_status == "SUCCESS")
df_sim = df_after_sol if is_preview else df_sim_original

# ==============================================================================
# HÀNG 1: TÌNH TRẠNG HIỆN TẠI CỦA NHÀ MÁY (FACTORY CURRENT STATUS)
# ==============================================================================
st.markdown("## PHÒNG ĐIỀU HÀNH LOGISTICS NHÀ MÁY (CONTROL ROOM)")
st.caption(f"Mốc thời gian hiện tại: {current_time.strftime('%Y-%m-%d %H:%M')} | Khung dự báo: t = {horizon_option}")

# Thông báo nếu đang ở chế độ xem trước (Preview Mode)
if is_preview:
    st.markdown(f"""
    <div class="preview-alert-banner">
        <strong>CHẾ ĐỘ XEM TRƯỚC (PREVIEW MODE): ĐANG ÁP DỤNG PHƯƠNG ÁN ĐIỀU ĐỘ TỰ ĐỘNG</strong><br>
        Dữ liệu Workload và Storage bên dưới đã được cập nhật theo giải pháp: <em>{plan_solution.get('level', '')}</em>.
    </div>
    """, unsafe_allow_html=True)
    if st.button("Thoát chế độ Preview", type="secondary", key="btn_exit_preview_top"):
        st.session_state.preview_mode = False
        st.rerun()

if current_time in df_data.index:
    curr_row = df_data.loc[current_time]
    cur_w_in = float(curr_row['workload_inbound'])
    cur_w_out = float(curr_row['workload_outbound'])
    cur_s_in = float(curr_row['storage_inbound'])
    cur_s_buf = float(curr_row['storage_buffer'])
    cur_s_out = float(curr_row['storage_outbound'])
    cur_l_in = int(curr_row['labor_inbound'])
    cur_l_out = int(curr_row['labor_outbound'])
    cur_amr = int(curr_row['amr_active'])
else:
    cur_w_in, cur_w_out = 50.0, 60.0
    cur_s_in, cur_s_buf, cur_s_out = 50.0, 100.0, 50.0
    cur_l_in, cur_l_out, cur_amr = 3, 3, 4

st.markdown("#### TÌNH TRẠNG HIỆN TẠI CỦA NHÀ MÁY")

# Chú thích ý nghĩa các màu sắc hiển thị
st.markdown("""
<div class="status-legend-bar">
    <span style="font-weight: 600;">Chú thích màu sắc:</span>
    <span class="legend-item"><span class="legend-dot-green"></span> <strong>Xanh lá</strong>: Định biên nhân lực bình thường / Tồn kho an toàn (&lt; 80% sức chứa)</span>
    <span class="legend-item"><span class="legend-dot-red"></span> <strong>Đỏ</strong>: Cảnh báo quá tải / Nguy cơ nghẽn kho (&ge; 80% sức chứa)</span>
</div>
""", unsafe_allow_html=True)

col_kpi1, col_kpi2, col_kpi3, col_kpi4, col_kpi5 = st.columns(5)

# Workload Inbound
col_kpi1.metric(
    label="Workload Inbound",
    value=f"{cur_w_in:.1f} pal/h",
    delta=f"Nhân công: {cur_l_in} người"
)

# Workload Outbound
col_kpi2.metric(
    label="Workload Outbound",
    value=f"{cur_w_out:.1f} pal/h",
    delta=f"Nhân công: {cur_l_out} | AMR: {cur_amr}"
)

# Storage Inbound
in_pct = (cur_s_in / MAX_STORAGE_INBOUND) * 100
col_kpi3.metric(
    label="Tồn kho Sàn Inbound",
    value=f"{cur_s_in:.1f} / {MAX_STORAGE_INBOUND}",
    delta=f"{in_pct:.1f}% sức chứa",
    delta_color="inverse" if cur_s_in >= WARN_STORAGE_INBOUND else "normal"
)

# Storage Buffer
buf_pct = (cur_s_buf / MAX_STORAGE_BUFFER) * 100
col_kpi4.metric(
    label="Tồn kho Kitting Buffer",
    value=f"{cur_s_buf:.1f} / {MAX_STORAGE_BUFFER}",
    delta=f"{buf_pct:.1f}% sức chứa",
    delta_color="inverse" if cur_s_buf >= WARN_STORAGE_BUFFER else "normal"
)

# Storage Outbound
out_pct = (cur_s_out / MAX_STORAGE_OUTBOUND) * 100
col_kpi5.metric(
    label="Tồn kho Sàn Outbound",
    value=f"{cur_s_out:.1f} / {MAX_STORAGE_OUTBOUND}",
    delta=f"{out_pct:.1f}% sức chứa",
    delta_color="inverse" if cur_s_out >= WARN_STORAGE_OUTBOUND else "normal"
)

st.markdown("---")

# ==============================================================================
# HÀNG 2: 2 BẢNG DỰ BÁO WORKLOAD (INBOUND & OUTBOUND) TRONG KHOẢNG THỜI GIAN t
# ==============================================================================
workload_header_tag = " (ĐANG XEM PREVIEW ĐIỀU ĐỘ)" if is_preview else ""
st.markdown(f"### DỰ BÁO KHỐI LƯỢNG CÔNG VIỆC TRONG {horizon_option} TỚI{workload_header_tag}")

col_w_in, col_w_out = st.columns(2)

# Chuỗi thời gian nối liền không khoảng cách giữa thực tế và dự báo
connect_time_idx = [history_df.index[-1]] + list(df_sim.index)
connect_w_in = [history_df["workload_inbound"].iloc[-1]] + list(df_sim["workload_inbound"])
connect_w_out = [history_df["workload_outbound"].iloc[-1]] + list(df_sim["workload_outbound"])

# --- BẢNG 1: DỰ BÁO WORKLOAD INBOUND ---
with col_w_in:
    st.markdown("#### Bảng 1: Dự báo Workload Inbound")
    tbl_w_in = pd.DataFrame({
        "Mốc giờ": [t.strftime("%H:%M %d/%m") for t in df_sim.index],
        "Dự báo (pallets/h)": df_sim["workload_inbound"].round(1),
        "Nhân công (người)": df_sim["labor_inbound"].astype(int),
        "Năng lực dỡ (pallets/h)": (df_sim["labor_inbound"] * RATE_LABOR_INBOUND).round(1),
    })
    tbl_w_in["Tải / Năng lực (%)"] = (
        (tbl_w_in["Dự báo (pallets/h)"] / tbl_w_in["Năng lực dỡ (pallets/h)"]) * 100
    ).round(1)
    st.dataframe(tbl_w_in, use_container_width=True, hide_index=True)

    if show_charts:
        fig_w_in, ax1 = plt.subplots(figsize=(7, 3.2))
        ax1.plot(
            history_df.index,
            history_df["workload_inbound"],
            color="#2c3e50",
            marker="o",
            linewidth=2,
            label="Thực tế (5h trước)"
        )
        # Nối liền từ điểm thực tế cuối cùng
        ax1.plot(
            connect_time_idx,
            connect_w_in,
            color="#2980b9",
            linestyle="--",
            linewidth=2,
            label=f"Dự báo {horizon_option}" + (" (Preview)" if is_preview else "")
        )
        ax1.plot(
            df_sim.index,
            df_sim["workload_inbound"],
            color="#2980b9",
            marker="s",
            linestyle="None"
        )
        ax1.axvline(x=current_time, color="gray", linestyle=":", label="Hiện tại")
        ax1.set_ylabel("Pallets/h")
        ax1.grid(True, linestyle="--", alpha=0.4)
        ax1.legend(loc="upper right", fontsize=8)
        fig_w_in.autofmt_xdate()
        st.pyplot(fig_w_in)
        plt.close(fig_w_in)

# --- BẢNG 2: DỰ BÁO WORKLOAD OUTBOUND ---
with col_w_out:
    st.markdown("#### Bảng 2: Dự báo Workload Outbound")
    tbl_w_out = pd.DataFrame({
        "Mốc giờ": [t.strftime("%H:%M %d/%m") for t in df_sim.index],
        "Dự báo (pallets/h)": df_sim["workload_outbound"].round(1),
        "Nhân công (người)": df_sim["labor_outbound"].astype(int),
        "Số xe AMR": df_sim["amr_active"].astype(int),
        "Năng lực xuất (pallets/h)": (df_sim["labor_outbound"] * RATE_LABOR_OUTBOUND).round(1),
    })
    tbl_w_out["Tải / Năng lực (%)"] = (
        (tbl_w_out["Dự báo (pallets/h)"] / tbl_w_out["Năng lực xuất (pallets/h)"]) * 100
    ).round(1)
    st.dataframe(tbl_w_out, use_container_width=True, hide_index=True)

    if show_charts:
        fig_w_out, ax2 = plt.subplots(figsize=(7, 3.2))
        ax2.plot(
            history_df.index,
            history_df["workload_outbound"],
            color="#2c3e50",
            marker="o",
            linewidth=2,
            label="Thực tế (5h trước)"
        )
        # Nối liền từ điểm thực tế cuối cùng
        ax2.plot(
            connect_time_idx,
            connect_w_out,
            color="#27ae60",
            linestyle="--",
            linewidth=2,
            label=f"Dự báo {horizon_option}" + (" (Preview)" if is_preview else "")
        )
        ax2.plot(
            df_sim.index,
            df_sim["workload_outbound"],
            color="#27ae60",
            marker="s",
            linestyle="None"
        )
        ax2.axvline(x=current_time, color="gray", linestyle=":", label="Hiện tại")
        ax2.set_ylabel("Pallets/h")
        ax2.grid(True, linestyle="--", alpha=0.4)
        ax2.legend(loc="upper right", fontsize=8)
        fig_w_out.autofmt_xdate()
        st.pyplot(fig_w_out)
        plt.close(fig_w_out)

st.markdown("---")

# ==============================================================================
# HÀNG 3: 3 BẢNG DỰ BÁO STORAGE (INBOUND, BUFFER, OUTBOUND) TRONG KHOẢNG THỜI GIAN t
# ==============================================================================
storage_header_tag = " (ĐANG XEM PREVIEW ĐIỀU ĐỘ)" if is_preview else ""
st.markdown(f"### MÔ PHỎNG DÒNG CHẢY VÀ SỨC CHỨA KHO TRONG {horizon_option} TỚI{storage_header_tag}")

col_s_in, col_s_buf, col_s_out = st.columns(3)

def evaluate_status(val, warn, maximum):
    if val >= maximum:
        return "Quá tải"
    elif val >= warn:
        return "Cảnh báo"
    return "An toàn"

# Chuỗi thời gian nối liền cho Storage
connect_s_in = [history_df["storage_inbound"].iloc[-1]] + list(df_sim["storage_inbound_sim"])
connect_s_buf = [history_df["storage_buffer"].iloc[-1]] + list(df_sim["storage_buffer_sim"])
connect_s_out = [history_df["storage_outbound"].iloc[-1]] + list(df_sim["storage_outbound_sim"])

# --- BẢNG 3: STORAGE INBOUND ---
with col_s_in:
    st.markdown("#### Bảng 3: Tồn kho Sàn Inbound")
    tbl_s_in = pd.DataFrame({
        "Mốc giờ": [t.strftime("%H:%M %d/%m") for t in df_sim.index],
        "Tồn kho (pallets)": df_sim["storage_inbound_sim"].round(1),
        "Cảnh báo (80%)": WARN_STORAGE_INBOUND,
        "Trần chứa": MAX_STORAGE_INBOUND,
        "Đánh giá": [evaluate_status(v, WARN_STORAGE_INBOUND, MAX_STORAGE_INBOUND) for v in df_sim["storage_inbound_sim"]]
    })
    st.dataframe(tbl_s_in, use_container_width=True, hide_index=True)

    if show_charts:
        fig_s_in, ax3 = plt.subplots(figsize=(5.5, 3.0))
        ax3.plot(history_df.index, history_df["storage_inbound"], color="#8e44ad", marker="o", linewidth=2, label="Quá khứ")
        ax3.plot(connect_time_idx, connect_s_in, color="#9b59b6", linestyle="--", linewidth=2, label="Mô phỏng")
        ax3.plot(df_sim.index, df_sim["storage_inbound_sim"], color="#9b59b6", marker="s", linestyle="None")
        ax3.axhline(y=WARN_STORAGE_INBOUND, color="#f39c12", linestyle="--", label=f"Cảnh báo ({WARN_STORAGE_INBOUND:.0f})")
        ax3.axhline(y=MAX_STORAGE_INBOUND, color="#c0392b", linestyle="-", label=f"Trần ({MAX_STORAGE_INBOUND})")
        ax3.set_ylabel("Pallets")
        ax3.grid(True, linestyle="--", alpha=0.4)
        ax3.legend(loc="upper right", fontsize=7)
        fig_s_in.autofmt_xdate()
        st.pyplot(fig_s_in)
        plt.close(fig_s_in)

# --- BẢNG 4: STORAGE BUFFER ---
with col_s_buf:
    st.markdown("#### Bảng 4: Tồn kho Kitting Buffer")
    tbl_s_buf = pd.DataFrame({
        "Mốc giờ": [t.strftime("%H:%M %d/%m") for t in df_sim.index],
        "Tồn kho (khay/thùng)": df_sim["storage_buffer_sim"].round(1),
        "Cảnh báo (80%)": WARN_STORAGE_BUFFER,
        "Trần chứa": MAX_STORAGE_BUFFER,
        "Đánh giá": [evaluate_status(v, WARN_STORAGE_BUFFER, MAX_STORAGE_BUFFER) for v in df_sim["storage_buffer_sim"]]
    })
    st.dataframe(tbl_s_buf, use_container_width=True, hide_index=True)

    if show_charts:
        fig_s_buf, ax4 = plt.subplots(figsize=(5.5, 3.0))
        ax4.plot(history_df.index, history_df["storage_buffer"], color="#d35400", marker="o", linewidth=2, label="Quá khứ")
        ax4.plot(connect_time_idx, connect_s_buf, color="#e67e22", linestyle="--", linewidth=2, label="Mô phỏng")
        ax4.plot(df_sim.index, df_sim["storage_buffer_sim"], color="#e67e22", marker="s", linestyle="None")
        ax4.axhline(y=WARN_STORAGE_BUFFER, color="#f39c12", linestyle="--", label=f"Cảnh báo ({WARN_STORAGE_BUFFER:.0f})")
        ax4.axhline(y=MAX_STORAGE_BUFFER, color="#c0392b", linestyle="-", label=f"Trần ({MAX_STORAGE_BUFFER})")
        ax4.set_ylabel("Khay/Thùng")
        ax4.grid(True, linestyle="--", alpha=0.4)
        ax4.legend(loc="upper right", fontsize=7)
        fig_s_buf.autofmt_xdate()
        st.pyplot(fig_s_buf)
        plt.close(fig_s_buf)

# --- BẢNG 5: STORAGE OUTBOUND ---
with col_s_out:
    st.markdown("#### Bảng 5: Tồn kho Sàn Outbound")
    tbl_s_out = pd.DataFrame({
        "Mốc giờ": [t.strftime("%H:%M %d/%m") for t in df_sim.index],
        "Tồn kho (pallets)": df_sim["storage_outbound_sim"].round(1),
        "Cảnh báo (80%)": WARN_STORAGE_OUTBOUND,
        "Trần chứa": MAX_STORAGE_OUTBOUND,
        "Đánh giá": [evaluate_status(v, WARN_STORAGE_OUTBOUND, MAX_STORAGE_OUTBOUND) for v in df_sim["storage_outbound_sim"]]
    })
    st.dataframe(tbl_s_out, use_container_width=True, hide_index=True)

    if show_charts:
        fig_s_out, ax5 = plt.subplots(figsize=(5.5, 3.0))
        ax5.plot(history_df.index, history_df["storage_outbound"], color="#2c3e50", marker="o", linewidth=2, label="Quá khứ")
        ax5.plot(connect_time_idx, connect_s_out, color="#7f8c8d", linestyle="--", linewidth=2, label="Mô phỏng")
        ax5.plot(df_sim.index, df_sim["storage_outbound_sim"], color="#7f8c8d", marker="s", linestyle="None")
        ax5.axhline(y=WARN_STORAGE_OUTBOUND, color="#f39c12", linestyle="--", label=f"Cảnh báo ({WARN_STORAGE_OUTBOUND:.0f})")
        ax5.axhline(y=MAX_STORAGE_OUTBOUND, color="#c0392b", linestyle="-", label=f"Trần ({MAX_STORAGE_OUTBOUND})")
        ax5.set_ylabel("Pallets")
        ax5.grid(True, linestyle="--", alpha=0.4)
        ax5.legend(loc="upper right", fontsize=7)
        fig_s_out.autofmt_xdate()
        st.pyplot(fig_s_out)
        plt.close(fig_s_out)

st.markdown("---")

# ==============================================================================
# HÀNG 4: PHÂN TÍCH ĐIỂM NGHẼN & ĐỀ XUẤT ĐIỀU ĐỘ (CÓ BUTTON PREVIEW)
# ==============================================================================
if run_capacity_solve:
    st.markdown("### PHÂN TÍCH VÀ ĐIỀU ĐỘ NĂNG LỰC (CAPACITY OPTIMIZATION)")
    bottlenecks_orig = capacity_engine.scan_bottlenecks(df_sim_original)

    if not bottlenecks_orig:
        st.success(f"Trạng thái vận hành ổn định trong {horizon_option} tới. Không phát hiện điểm nghẽn kho vượt ngưỡng an toàn.")
    else:
        st.warning(f"Cảnh báo: Phát hiện {len(bottlenecks_orig)} mốc thời gian có nguy cơ nghẽn kho trong kế hoạch gốc.")
        
        # Bảng chi tiết các điểm nghẽn gốc
        df_bn = pd.DataFrame(bottlenecks_orig)
        df_bn.columns = ["Chỉ số bước", "Mốc giờ", "Khu vực nghẽn", "Mức độ vượt ngưỡng (pallets/khay)"]
        st.dataframe(df_bn, use_container_width=True, hide_index=True)

        st.markdown("#### Đề xuất phương án điều phối tự động")
        
        sol_col1, sol_col2, sol_col3 = st.columns([1.2, 1.8, 1.0])
        
        with sol_col1:
            st.info(f"Trạng thái: {solution_status}\n\nCấp độ can thiệp: {plan_solution.get('level', 'N/A')}\n\nChi phí nhân công: {plan_solution.get('cost', 0)} man-hours")

        with sol_col2:
            st.markdown("**Các bước hành động chi tiết:**")
            action_logs = plan_solution.get('action_logs', [])
            if action_logs:
                for log in action_logs:
                    st.write(f"- {log}")
            else:
                st.write(plan_solution.get('message', 'Không có hành động bổ sung.'))

        with sol_col3:
            st.markdown("**Chế độ xem trước:**")
            if solution_status == "SUCCESS":
                if not st.session_state.preview_mode:
                    if st.button("Mở chế độ Preview", type="primary", use_container_width=True):
                        st.session_state.preview_mode = True
                        st.rerun()
                    st.caption("Xem dự báo và dòng chảy kho sau khi áp dụng phương án.")
                else:
                    if st.button("Đóng chế độ Preview", type="secondary", use_container_width=True):
                        st.session_state.preview_mode = False
                        st.rerun()
                    st.caption("Đang xem kết quả sau điều độ.")
            else:
                st.button("Không khả dụng Preview", disabled=True, use_container_width=True)

        # ----------------------------------------------------------------------
        # NỘI DUNG KHOA HỌC KHI MỞ CHẾ ĐỘ PREVIEW (SO SÁNH CHI TIẾT TRƯỚC / SAU)
        # ----------------------------------------------------------------------
        if is_preview:
            st.markdown("#### ĐÁNH GIÁ HIỆU QUẢ CẢI THIỆN SAU KHI ĐIỀU ĐỘ (BEFORE vs AFTER)")
            
            df_b = df_sim_original
            df_a = df_after_sol
            bn_after = capacity_engine.scan_bottlenecks(df_a)
            
            # Tính toán các chỉ số cải thiện chính
            bn_reduction = len(bottlenecks_orig) - len(bn_after)
            max_in_b, max_in_a = df_b['storage_inbound_sim'].max(), df_a['storage_inbound_sim'].max()
            max_buf_b, max_buf_a = df_b['storage_buffer_sim'].max(), df_a['storage_buffer_sim'].max()
            max_out_b, max_out_a = df_b['storage_outbound_sim'].max(), df_a['storage_outbound_sim'].max()

            diff_in = max_in_a - max_in_b
            diff_buf = max_buf_a - max_buf_b
            diff_out = max_out_a - max_out_b

            col_met1, col_met2, col_met3, col_met4 = st.columns(4)
            col_met1.metric(
                "Điểm nghẽn kho",
                f"{len(bn_after)} điểm",
                delta=f"Giảm {bn_reduction} điểm nghẽn" if bn_reduction > 0 else "Giảm mức độ nghẽn",
                delta_color="normal"
            )
            col_met2.metric(
                "Đỉnh tồn kho Sàn Inbound",
                f"{max_in_a:.1f} pal",
                delta=f"{diff_in:+.1f} pal",
                delta_color="normal" if diff_in <= 0 else "inverse"
            )
            col_met3.metric(
                "Đỉnh tồn kho Kitting Buffer",
                f"{max_buf_a:.1f} khay",
                delta=f"{diff_buf:+.1f} khay",
                delta_color="normal" if diff_buf <= 0 else "inverse"
            )
            col_met4.metric(
                "Đỉnh tồn kho Sàn Outbound",
                f"{max_out_a:.1f} pal",
                delta=f"{diff_out:+.1f} pal",
                delta_color="normal" if diff_out <= 0 else "inverse"
            )

            # Bảng so sánh chi tiết từng giờ trước và sau can thiệp
            st.markdown("**Bảng phân tích so sánh chi tiết từng mốc giờ (Delta Analysis):**")
            comparison_rows = []
            for t in df_b.index:
                t_str = t.strftime("%H:%M %d/%m")
                w_in_b = df_b.loc[t, "workload_inbound"]
                w_in_a = df_a.loc[t, "workload_inbound"]
                s_in_b = df_b.loc[t, "storage_inbound_sim"]
                s_in_a = df_a.loc[t, "storage_inbound_sim"]
                s_buf_b = df_b.loc[t, "storage_buffer_sim"]
                s_buf_a = df_a.loc[t, "storage_buffer_sim"]
                s_out_b = df_b.loc[t, "storage_outbound_sim"]
                s_out_a = df_a.loc[t, "storage_outbound_sim"]
                l_in_b = int(df_b.loc[t, "labor_inbound"])
                l_in_a = int(df_a.loc[t, "labor_inbound"])
                l_out_b = int(df_b.loc[t, "labor_outbound"])
                l_out_a = int(df_a.loc[t, "labor_outbound"])

                # Ghi nhận thay đổi
                notes = []
                if l_in_a != l_in_b:
                    notes.append(f"Nhân công Inbound: {l_in_b} -> {l_in_a}")
                if l_out_a != l_out_b:
                    notes.append(f"Nhân công Outbound: {l_out_b} -> {l_out_a}")
                if w_in_a != w_in_b:
                    notes.append(f"Workload Inbound dời: {w_in_a - w_in_b:+.1f}")
                if s_in_a < s_in_b:
                    notes.append(f"Giảm tồn Inbound {s_in_b - s_in_a:.1f} pal")
                if s_buf_a < s_buf_b:
                    notes.append(f"Giảm tồn Buffer {s_buf_b - s_buf_a:.1f} khay")
                if s_out_a < s_out_b:
                    notes.append(f"Giảm tồn Outbound {s_out_b - s_out_a:.1f} pal")

                comparison_rows.append({
                    "Mốc giờ": t_str,
                    "Workload In (Trước -> Sau)": f"{w_in_b:.1f} -> {w_in_a:.1f}",
                    "Nhân sự In / Out (Sau)": f"{l_in_a} / {l_out_a} người",
                    "Tồn Inbound (Trước -> Sau)": f"{s_in_b:.1f} -> {s_in_a:.1f}",
                    "Tồn Buffer (Trước -> Sau)": f"{s_buf_b:.1f} -> {s_buf_a:.1f}",
                    "Tồn Outbound (Trước -> Sau)": f"{s_out_b:.1f} -> {s_out_a:.1f}",
                    "Ghi chú cải thiện": "; ".join(notes) if notes else "Ổn định"
                })

            df_comp = pd.DataFrame(comparison_rows)
            st.dataframe(df_comp, use_container_width=True, hide_index=True)
