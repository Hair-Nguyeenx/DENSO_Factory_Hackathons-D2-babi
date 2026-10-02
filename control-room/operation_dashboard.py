import os
import sys
import re
from pathlib import Path
import pandas as pd
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt

# Thiết lập đường dẫn thư mục linh hoạt (tương thích cả chạy độc lập hoặc theo module)
BASE_DIR = Path(__file__).resolve().parent.parent
PRED_DIR = BASE_DIR / "prediction-capacity-mode"
if not PRED_DIR.exists():
    PRED_DIR = Path(__file__).resolve().parent
    BASE_DIR = PRED_DIR

DATA_PATH = BASE_DIR / "denso_logistics_simulation_test.csv"
if not DATA_PATH.exists():
    DATA_PATH = PRED_DIR / "denso_logistics_simulation_test.csv"

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
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded"
)

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

# ==============================================================================
# KHỞI TẠO BỘ NHỚ TRẠNG THÁI BỀN VỮNG (PERSISTENT SESSION STATE)
# ==============================================================================
df_data = forecaster.df
timestamps_2027 = df_data.loc['2027'].index
default_time = pd.Timestamp("2027-01-05 08:00")
if default_time not in timestamps_2027:
    default_time = timestamps_2027[0]

# 0. Tab điều hướng chính (VẬN HÀNH / MÔ PHỎNG)
if 'active_main_tab' not in st.session_state:
    st.session_state['active_main_tab'] = "VẬN HÀNH"

# 1. Mốc thời gian vận hành hiện tại
if 'current_time' not in st.session_state:
    st.session_state['current_time'] = default_time

# 2. Lịch trình điều độ tổng thể đã phê duyệt (Master Schedule)
# Lưu trữ từng mốc thời gian t -> dict các thông số đã tối ưu (workload, labor, amr)
if 'master_schedule' not in st.session_state:
    st.session_state['master_schedule'] = {}

# 3. Lịch sử thực thi quá khứ (Executed History)
# Lưu lại đúng số liệu thực tế đã vận hành qua các giờ trước để vẽ biểu đồ và metric chính xác
if 'executed_history' not in st.session_state:
    st.session_state['executed_history'] = {}

# 4. Ghi nhận dịch chuyển Heijunka để bóc tách nhiễu cho AI (Zero Feedback Confounding)
if 'committed_heijunka_in' not in st.session_state:
    st.session_state['committed_heijunka_in'] = {}
if 'committed_heijunka_out' not in st.session_state:
    st.session_state['committed_heijunka_out'] = {}

# 5. Tồn kho chuyển tiếp giữa các ca (Ending stock of t -> Beginning stock of t+1)
if 'simulated_stocks' not in st.session_state:
    st.session_state['simulated_stocks'] = None

# ==============================================================================
# THANH ĐIỀU KHIỂN (SIDEBAR)
# ==============================================================================
st.sidebar.markdown("### BẢNG ĐIỀU KHIỂN")

theme_choice = st.sidebar.radio(
    "Chế độ giao diện (Theme)",
    options=["🌙 Giao diện Tối (Dark)", "☀️ Giao diện Sáng (Light)"],
    index=0
) 
is_light = "Sáng" in theme_choice

st.sidebar.markdown("---")
st.sidebar.markdown("#### Điều khiển thời gian vận hành")

curr_t = st.session_state['current_time']
st.sidebar.info(f"Thời gian hiện tại: **{curr_t.strftime('%H:%M %d/%m/%Y')}**")

# XÁC ĐỊNH SỐ LIỆU TỒN KHO VÀ DỰ BÁO TRƯỚC KHI THỰC HIỆN NÚT BƯỚC SANG GIỜ MỚI
horizon_option = st.sidebar.radio(
    "Chọn khoảng thời gian dự báo",
    options=["1h", "3h", "12h"],
    index=1
)
horizon_val = int(horizon_option.replace("h", ""))

# Đồng bộ Date Picker & Slider với current_time từ session_state

# Đồng bộ Date Picker & Slider với current_time từ session_state
selected_date = st.sidebar.date_input(
    "Chọn ngày vận hành",
    value=st.session_state['current_time'].date(),
    min_value=timestamps_2027[0].date(),
    max_value=timestamps_2027[-1].date()
)

selected_hour = st.sidebar.slider(
    "Chọn giờ vận hành",
    min_value=0,
    max_value=23,
    value=int(st.session_state['current_time'].hour),
    step=1,
    format="%02d:00"
)

new_time_pick = pd.Timestamp(f"{selected_date} {selected_hour:02d}:00:00")
if new_time_pick != st.session_state['current_time']:
    st.session_state['current_time'] = new_time_pick
    if new_time_pick in st.session_state['master_schedule']:
        sched = st.session_state['master_schedule'][new_time_pick]
        st.session_state['simulated_stocks'] = (
            float(sched['storage_inbound_sim']),
            float(sched['storage_buffer_sim']),
            float(sched['storage_outbound_sim'])
        )
    else:
        st.session_state['simulated_stocks'] = None
    st.rerun()

current_time = st.session_state['current_time']

st.sidebar.markdown("---")
show_charts = st.sidebar.checkbox("Hiển thị biểu đồ trực quan", value=True)
run_capacity_solve = st.sidebar.checkbox("Phân tích điều độ giải phóng nghẽn", value=True)

# ==============================================================================
# HỆ THỐNG GIAO DIỆN & CSS (DARK & LIGHT MODE)
# ==============================================================================
if is_light:
    theme_css = """
    <style>
    .stApp { background-color: #f8fafc !important; color: #000000 !important; }
    header[data-testid="stHeader"] { background-color: #f8fafc !important; }
    [data-testid="stSidebar"] { background-color: #ffffff !important; border-right: 1.5px solid #cbd5e1 !important; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p, [data-testid="stSidebar"] label, [data-testid="stSidebar"] span { color: #000000 !important; font-weight: 600 !important; }
    h1, h2, h3, h4, h5, h6 { color: #000000 !important; font-weight: 800 !important; }
    p, span, label, div { color: #000000; }
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: #000000 !important; font-weight: 500 !important; }
    [data-testid="stMetric"] { background: #ffffff !important; border: 1.5px solid #cbd5e1 !important; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05) !important; border-radius: 8px !important; padding: 10px 8px !important; }
    [data-testid="stMetricLabel"] p { color: #000000 !important; font-weight: 700 !important; font-size: 13px !important; white-space: nowrap !important; }
    [data-testid="stMetricValue"] > div { color: #000000 !important; font-weight: 800 !important; font-size: 19px !important; line-height: 1.25 !important; }
    [data-testid="stMetricDelta"] > div { font-size: 11.5px !important; white-space: nowrap !important; font-weight: 600 !important; }
    [data-testid="stDateInput"] div[data-baseweb="input"], div[data-baseweb="input"] { background-color: #ffffff !important; border: 1.5px solid #94a3b8 !important; border-radius: 6px !important; outline: none !important; }
    [data-testid="stDateInput"] input, div[data-baseweb="input"] input { color: #000000 !important; font-weight: 600 !important; font-size: 14px !important; }
    [data-testid="stDateInput"] svg, div[data-baseweb="input"] svg { fill: #000000 !important; color: #000000 !important; }
    
    /* Calendar popover & day cells: border-radius 50% circular hover and selection without square artifacts */
    div[data-baseweb="popover"], div[data-baseweb="popover"] > div, div[data-baseweb="calendar"] { background-color: #ffffff !important; color: #000000 !important; border-radius: 12px !important; }
    div[data-baseweb="calendar"] header, div[data-baseweb="calendar"] header * { background-color: transparent !important; color: #000000 !important; }
    div[data-baseweb="calendar"] [role="gridcell"] { background-color: transparent !important; }
    div[data-baseweb="calendar"] [role="gridcell"] * { background-color: transparent !important; color: #000000 !important; }
    div[data-baseweb="calendar"] [role="gridcell"] > div, div[data-baseweb="calendar"] button { border-radius: 50% !important; }
    div[data-baseweb="calendar"] [role="gridcell"] > div:hover, div[data-baseweb="calendar"] button:hover { background-color: #e2e8f0 !important; border-radius: 50% !important; color: #000000 !important; }
    div[data-baseweb="calendar"] [aria-selected="true"], div[data-baseweb="calendar"] [role="gridcell"] > div[aria-selected="true"] { background-color: #ef4444 !important; border-radius: 50% !important; color: #ffffff !important; font-weight: 700 !important; }
    div[data-baseweb="calendar"] [aria-selected="true"] * { color: #ffffff !important; background-color: transparent !important; }
    
    div[data-testid="stRadio"] label p { color: #000000 !important; font-weight: 600 !important; }
    div[data-testid="stCheckbox"] label p { color: #000000 !important; font-weight: 600 !important; }
    [data-testid="stDialog"] div[role="dialog"] { background-color: #ffffff !important; color: #000000 !important; border: 2px solid #94a3b8 !important; border-radius: 12px !important; }
    [data-testid="stDialog"] div[role="dialog"] * { color: #000000 !important; }
    [data-testid="stDialog"] button[aria-label="Close"] { color: #000000 !important; }
    [data-testid="stButton"] button[kind="primary"], button[data-testid="stBaseButton-primary"] { color: #ffffff !important; background-color: #ef4444 !important; border: none !important; font-weight: 700 !important; }
    [data-testid="stButton"] button[kind="primary"] * { color: #ffffff !important; font-weight: 700 !important; }
    [data-testid="stButton"] button[kind="secondary"], button[data-testid="stBaseButton-secondary"] { color: #000000 !important; background-color: #ffffff !important; border: 1.5px solid #000000 !important; font-weight: 700 !important; }
    [data-testid="stButton"] button[kind="secondary"] * { color: #000000 !important; font-weight: 700 !important; }
    
    /* Prominent Cancel Plan button */
    .cancel-plan-btn button {
        background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%) !important;
        color: #ffffff !important;
        border: 1.5px solid #ef4444 !important;
        box-shadow: 0 4px 12px rgba(220, 38, 38, 0.45) !important;
        font-weight: 800 !important;
        font-size: 13.5px !important;
        border-radius: 8px !important;
        padding: 8px 14px !important;
        letter-spacing: 0.2px !important;
        transition: all 0.2s ease !important;
    }
    .cancel-plan-btn button:hover {
        background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%) !important;
        box-shadow: 0 6px 18px rgba(220, 38, 38, 0.65) !important;
        transform: translateY(-1px) !important;
    }
    .cancel-plan-btn button * {
        color: #ffffff !important;
        font-weight: 800 !important;
    }

    hr { border-color: #cbd5e1 !important; }
    .styled-table-wrapper { scrollbar-width: thin; scrollbar-color: #94a3b8 rgba(0, 0, 0, 0.05); }
    .styled-table-wrapper::-webkit-scrollbar { height: 7px; }
    .styled-table-wrapper::-webkit-scrollbar-track { background: #f1f5f9; border-radius: 4px; }
    .styled-table-wrapper::-webkit-scrollbar-thumb { background: #94a3b8; border-radius: 4px; }
    </style>
    """
else:
    theme_css = """
    <style>
    .stApp { background-color: #0b0f19 !important; color: #ffffff !important; }
    header[data-testid="stHeader"] { background-color: #0b0f19 !important; }
    [data-testid="stSidebar"] { background-color: #111827 !important; border-right: 1.5px solid #1f293d !important; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p, [data-testid="stSidebar"] label, [data-testid="stSidebar"] span { color: #ffffff !important; font-weight: 600 !important; }
    h1, h2, h3, h4, h5, h6 { color: #ffffff !important; font-weight: 800 !important; }
    p, span, label, div { color: #ffffff; }
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: #ffffff !important; font-weight: 500 !important; }
    [data-testid="stMetric"] { background: #141c2e !important; border: 1.5px solid #233148 !important; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3) !important; border-radius: 8px !important; padding: 10px 8px !important; }
    [data-testid="stMetricLabel"] p { color: #ffffff !important; font-weight: 700 !important; font-size: 13px !important; white-space: nowrap !important; }
    [data-testid="stMetricValue"] > div { color: #ffffff !important; font-weight: 800 !important; font-size: 19px !important; line-height: 1.25 !important; }
    [data-testid="stMetricDelta"] > div { font-size: 11.5px !important; white-space: nowrap !important; font-weight: 600 !important; }
    [data-testid="stDateInput"] div[data-baseweb="input"], div[data-baseweb="input"] { background-color: #161f30 !important; border: 1.5px solid #334155 !important; border-radius: 6px !important; outline: none !important; }
    [data-testid="stDateInput"] input, div[data-baseweb="input"] input { color: #ffffff !important; font-weight: 600 !important; font-size: 14px !important; }
    [data-testid="stDateInput"] svg, div[data-baseweb="input"] svg { fill: #ffffff !important; color: #ffffff !important; }
    
    /* Calendar popover & day cells: border-radius 50% circular hover and selection without square artifacts */
    div[data-baseweb="popover"], div[data-baseweb="popover"] > div, div[data-baseweb="calendar"] { background-color: #111827 !important; color: #ffffff !important; border: 1px solid #374151 !important; border-radius: 12px !important; }
    div[data-baseweb="calendar"] header, div[data-baseweb="calendar"] header * { background-color: transparent !important; color: #ffffff !important; }
    div[data-baseweb="calendar"] [role="gridcell"] { background-color: transparent !important; }
    div[data-baseweb="calendar"] [role="gridcell"] * { background-color: transparent !important; color: #ffffff !important; }
    div[data-baseweb="calendar"] [role="gridcell"] > div, div[data-baseweb="calendar"] button { border-radius: 50% !important; }
    div[data-baseweb="calendar"] [role="gridcell"] > div:hover, div[data-baseweb="calendar"] button:hover { background-color: #374151 !important; border-radius: 50% !important; color: #ffffff !important; }
    div[data-baseweb="calendar"] [aria-selected="true"], div[data-baseweb="calendar"] [role="gridcell"] > div[aria-selected="true"] { background-color: #ef4444 !important; border-radius: 50% !important; color: #ffffff !important; font-weight: 700 !important; }
    div[data-baseweb="calendar"] [aria-selected="true"] * { color: #ffffff !important; background-color: transparent !important; }

    div[data-testid="stRadio"] label p { color: #ffffff !important; font-weight: 600 !important; }
    div[data-testid="stCheckbox"] label p { color: #ffffff !important; font-weight: 600 !important; }
    [data-testid="stDialog"] div[role="dialog"] { background-color: #111827 !important; color: #ffffff !important; border: 2px solid #374151 !important; border-radius: 12px !important; }
    [data-testid="stDialog"] div[role="dialog"] * { color: #ffffff !important; }
    [data-testid="stDialog"] button[aria-label="Close"] { color: #ffffff !important; }
    [data-testid="stButton"] button[kind="primary"], button[data-testid="stBaseButton-primary"] { color: #ffffff !important; background-color: #ef4444 !important; border: none !important; font-weight: 700 !important; }
    [data-testid="stButton"] button[kind="primary"] * { color: #ffffff !important; font-weight: 700 !important; }
    [data-testid="stButton"] button[kind="secondary"], button[data-testid="stBaseButton-secondary"] { color: #ffffff !important; background-color: #1e293b !important; border: 1.5px solid #ffffff !important; font-weight: 700 !important; }
    [data-testid="stButton"] button[kind="secondary"] * { color: #ffffff !important; font-weight: 700 !important; }
    
    /* Prominent Cancel Plan button */
    .cancel-plan-btn button {
        background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%) !important;
        color: #ffffff !important;
        border: 1.5px solid #ef4444 !important;
        box-shadow: 0 4px 12px rgba(220, 38, 38, 0.45) !important;
        font-weight: 800 !important;
        font-size: 13.5px !important;
        border-radius: 8px !important;
        padding: 8px 14px !important;
        letter-spacing: 0.2px !important;
        transition: all 0.2s ease !important;
    }
    .cancel-plan-btn button:hover {
        background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%) !important;
        box-shadow: 0 6px 18px rgba(220, 38, 38, 0.65) !important;
        transform: translateY(-1px) !important;
    }
    .cancel-plan-btn button * {
        color: #ffffff !important;
        font-weight: 800 !important;
    }

    hr { border-color: #1f293d !important; }
    .styled-table-wrapper { scrollbar-width: thin; scrollbar-color: #475569 rgba(255, 255, 255, 0.05); }
    .styled-table-wrapper::-webkit-scrollbar { height: 7px; }
    .styled-table-wrapper::-webkit-scrollbar-track { background: #0f172a; border-radius: 4px; }
    .styled-table-wrapper::-webkit-scrollbar-thumb { background: #475569; border-radius: 4px; }
    </style>
    """

common_css = """
<style>
[data-testid='stMetricDelta'] svg { display: none !important; }
.block-container, [data-testid="block-container"], [data-testid="stMainBlockContainer"] {
    padding-top: 1.0rem !important;
    padding-bottom: 2.5rem !important;
}
header[data-testid="stHeader"] {
    height: 1.2rem !important;
    background: transparent !important;
}
.top-nav-tabs button {
    height: 48px !important;
    font-size: 15px !important;
    font-weight: 800 !important;
    letter-spacing: 0.8px !important;
    border-radius: 8px !important;
    transition: all 0.2s ease !important;
}
.top-nav-tabs button:hover {
    transform: translateY(-1px) !important;
}
</style>
"""
st.markdown(theme_css + common_css, unsafe_allow_html=True)

def format_action_log(log_str: str) -> str:
    """Đảm bảo các đại lượng số (pallets, khay, người, xe, công nhân) luôn là số nguyên sạch sẽ."""
    if not isinstance(log_str, str):
        return str(log_str)
    def _repl(match):
        val = float(match.group(1))
        unit = match.group(2)
        return f"{int(round(val))} {unit}"
    return re.sub(
        r'(\d+(?:\.\d+)?)\s*(pallets?|khay|thùng|kiện|xe|người|công nhân)',
        _repl,
        log_str,
        flags=re.IGNORECASE
    )

# ==============================================================================
# HÀM HIỂN THỊ BẢNG DỮ LIỆU ĐƯỢC THIẾT KẾ CÓ VIỀN VÀ THANH CUỘN NGANG
# ==============================================================================
def render_styled_table(df: pd.DataFrame, is_light_theme: bool = False, min_width: str = "540px") -> str:
    if is_light_theme:
        border_outer = "#94a3b8"
        border_cell = "#cbd5e1"
        header_bg = "#e2e8f0"
        header_text = "#000000"
        row_even = "#ffffff"
        row_odd = "#f8fafc"
        cell_text = "#000000"
    else:
        border_outer = "#475569"
        border_cell = "#26354a"
        header_bg = "#1e293b"
        header_text = "#ffffff"
        row_even = "#0f172a"
        row_odd = "#162032"
        cell_text = "#ffffff"

    html = f"""
    <div class="styled-table-wrapper" style="width: 100%; border-radius: 8px; overflow-x: auto; overflow-y: hidden; border: 1.5px solid {border_outer}; margin-bottom: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.06);">
      <table style="width: 100%; min-width: {min_width}; border-collapse: collapse; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 12.5px; text-align: left;">
        <thead>
          <tr style="background-color: {header_bg};">
    """
    for col in df.columns:
        col_str = str(col).lower()
        if any(k in col_str for k in ["mốc giờ", "chỉ số", "đánh giá", "nhân", "xe"]):
            align = "center"
        elif any(k in col_str for k in ["dự báo", "tồn", "năng lực", "tải", "ngưỡng", "trần", "cảnh báo"]):
            align = "right"
        else:
            align = "left"
        html += f"""<th style="padding: 9px 10px; color: {header_text}; font-weight: 800; font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.3px; border-bottom: 2px solid {border_outer}; border-right: 1px solid {border_cell}; text-align: {align}; white-space: nowrap;">{col}</th>"""
    
    html += """</tr></thead><tbody>"""

    for i, (_, row) in enumerate(df.iterrows()):
        bg = row_even if i % 2 == 0 else row_odd
        html += f"""<tr style="background-color: {bg}; border-bottom: 1px solid {border_cell};">"""
        for col in df.columns:
            val = row[col]
            col_str = str(col).lower()
            if any(k in col_str for k in ["mốc giờ", "chỉ số", "đánh giá", "nhân", "xe"]):
                align = "center"
            elif any(k in col_str for k in ["dự báo", "tồn", "năng lực", "tải", "ngưỡng", "trần", "cảnh báo"]):
                align = "right"
            else:
                align = "left"
            
            if col == "Đánh giá":
                if val == "An toàn":
                    cell_content = '<span style="background: rgba(16, 185, 129, 0.2); color: #059669; border: 1px solid #10b981; padding: 2px 8px; border-radius: 4px; font-weight: 700; font-size: 11.5px;">✓ An toàn</span>'
                elif val == "Cảnh báo":
                    cell_content = '<span style="background: rgba(245, 158, 11, 0.2); color: #d97706; border: 1px solid #f59e0b; padding: 2px 8px; border-radius: 4px; font-weight: 700; font-size: 11.5px;">⚠ Cảnh báo</span>'
                else:
                    cell_content = '<span style="background: rgba(239, 68, 68, 0.2); color: #dc2626; border: 1px solid #ef4444; padding: 2px 8px; border-radius: 4px; font-weight: 700; font-size: 11.5px;">⛔ Quá tải</span>'
            elif "Tải / Năng lực" in str(col):
                try:
                    pct_val = float(str(val).replace("%", ""))
                    if pct_val > 120.0:
                        cell_content = f'<span style="color: #ef4444; font-weight: 800;">{val}%</span>'
                    elif pct_val > 100.0:
                        cell_content = f'<span style="color: #f59e0b; font-weight: 700;">{val}%</span>'
                    else:
                        cell_content = f'<span style="color: #10b981; font-weight: 600;">{val}%</span>'
                except:
                    cell_content = str(val)
            elif col == "Khu vực nghẽn":
                cell_content = f'<strong style="color: #ef4444;">{str(val).upper()}</strong>'
            else:
                cell_content = str(val)

            html += f"""<td style="padding: 8px 10px; color: {cell_text}; border-right: 1px solid {border_cell}; text-align: {align}; font-variant-numeric: tabular-nums; white-space: nowrap;">{cell_content}</td>"""
        html += """</tr>"""

    html += """</tbody></table></div>"""
    return html

def apply_chart_theme_and_top_legend(fig, ax, ncol: int = 4, is_light_theme: bool = False):
    if is_light_theme:
        bg_color = "#ffffff"
        text_color = "#000000"
        grid_color = "#e2e8f0"
        spine_color = "#94a3b8"
    else:
        bg_color = "#111827"
        text_color = "#ffffff"
        grid_color = "#1f293d"
        spine_color = "#475569"

    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    ax.tick_params(colors=text_color, labelsize=8)
    ax.xaxis.label.set_color(text_color)
    ax.yaxis.label.set_color(text_color)
    for spine in ax.spines.values():
        spine.set_color(spine_color)
    ax.grid(True, linestyle="--", alpha=0.6, color=grid_color)

    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, 1.05),
        ncol=ncol,
        fontsize=7.6,
        frameon=False,
        handlelength=1.4,
        columnspacing=0.9,
        labelcolor=text_color
    )
    fig.subplots_adjust(top=0.83, bottom=0.22, left=0.13, right=0.96)
    fig.autofmt_xdate(rotation=30, ha="right")

# ==============================================================================
# TÍNH TOÁN DỰ BÁO VÀ DÒNG CHẢY KẾ THỪA LỊCH ĐIỀU ĐỘ
# ==============================================================================
# 0. Tự động dọn dẹp lưu động (Rolling Cleanup) các mốc giờ đã khuất khỏi biểu đồ (> 6h trước)
cutoff_time = current_time - pd.Timedelta(hours=6)
for old_t in list(st.session_state['master_schedule'].keys()):
    if old_t < cutoff_time:
        st.session_state['master_schedule'].pop(old_t, None)
for old_t in list(st.session_state['executed_history'].keys()):
    if old_t < cutoff_time:
        st.session_state['executed_history'].pop(old_t, None)
for old_t in list(st.session_state['committed_heijunka_in'].keys()):
    if old_t < cutoff_time:
        st.session_state['committed_heijunka_in'].pop(old_t, None)
for old_t in list(st.session_state['committed_heijunka_out'].keys()):
    if old_t < cutoff_time:
        st.session_state['committed_heijunka_out'].pop(old_t, None)

history_df, df_plan_natural, init_stocks_csv = forecaster.get_control_room_data(
    current_time=current_time,
    horizon=horizon_val,
    lookback=5
)

# 1. Chuyển kiểu dữ liệu các cột đo lường sang float64 để nhận giá trị số thực từ kế hoạch mà không bị lỗi ép kiểu Pandas
history_df = history_df.astype({
    'storage_inbound': 'float64',
    'storage_buffer': 'float64',
    'storage_outbound': 'float64',
    'workload_inbound': 'float64',
    'workload_outbound': 'float64'
}).copy()

# 2. Tồn kho khởi điểm hiện tại (init_stocks tại current_time):
# Ưu tiên 1: Kế thừa từ master_schedule nếu mốc current_time đã được giải tỏa/tối ưu trước đó
if current_time in st.session_state['master_schedule']:
    sched_curr = st.session_state['master_schedule'][current_time]
    init_stocks = (
        float(sched_curr['storage_inbound_sim']),
        float(sched_curr['storage_buffer_sim']),
        float(sched_curr['storage_outbound_sim'])
    )
# Ưu tiên 2: Kế thừa từ simulated_stocks nếu vừa bấm nút +1h
elif st.session_state['simulated_stocks'] is not None:
    init_stocks = st.session_state['simulated_stocks']
# Ưu tiên 3: Dữ liệu khởi điểm từ CSV
else:
    init_stocks = init_stocks_csv

# 3. Cập nhật toàn bộ các mốc giờ quá khứ còn hiển thị trên biểu đồ (5h trước)
for t in history_df.index:
    if t in st.session_state['executed_history']:
        rec = st.session_state['executed_history'][t]
        for col in ['workload_inbound', 'workload_outbound', 'storage_inbound', 'storage_buffer', 'storage_outbound']:
            if col in rec and col in history_df.columns:
                history_df.loc[t, col] = float(rec[col])
    elif t in st.session_state['master_schedule']:
        sched = st.session_state['master_schedule'][t]
        history_df.loc[t, 'storage_inbound'] = float(sched['storage_inbound_sim'])
        history_df.loc[t, 'storage_buffer'] = float(sched['storage_buffer_sim'])
        history_df.loc[t, 'storage_outbound'] = float(sched['storage_outbound_sim'])
        history_df.loc[t, 'workload_inbound'] = float(sched['workload_inbound'])
        history_df.loc[t, 'workload_outbound'] = float(sched['workload_outbound'])
        if 'labor_inbound' in history_df.columns: history_df.loc[t, 'labor_inbound'] = sched['labor_inbound']
        if 'labor_outbound' in history_df.columns: history_df.loc[t, 'labor_outbound'] = sched['labor_outbound']
        if 'amr_active' in history_df.columns: history_df.loc[t, 'amr_active'] = sched['amr_active']

# Ghi đè chính xác mốc hiện tại current_time (điểm cuối của history_df):
# Tồn kho bắt buộc phải khớp 100% với init_stocks thực tế
history_df.loc[current_time, 'storage_inbound'] = float(init_stocks[0])
history_df.loc[current_time, 'storage_buffer'] = float(init_stocks[1])
history_df.loc[current_time, 'storage_outbound'] = float(init_stocks[2])

if current_time in st.session_state['master_schedule']:
    sched_curr = st.session_state['master_schedule'][current_time]
    history_df.loc[current_time, 'workload_inbound'] = float(sched_curr['workload_inbound'])
    history_df.loc[current_time, 'workload_outbound'] = float(sched_curr['workload_outbound'])
elif current_time in st.session_state['committed_heijunka_in']:
    d_in = st.session_state['committed_heijunka_in'][current_time]
    history_df.loc[current_time, 'workload_inbound'] = max(0.0, float(history_df.loc[current_time, 'workload_inbound']) + d_in)

# 4. Xây dựng df_plan: Tự động kế thừa các mốc giờ đã được phê duyệt trong master_schedule
df_plan = df_plan_natural.copy()
active_planned_hours = []

for t in df_plan.index:
    if t in st.session_state['master_schedule']:
        active_planned_hours.append(t)
        sched = st.session_state['master_schedule'][t]
        df_plan.loc[t, 'workload_inbound'] = sched['workload_inbound']
        df_plan.loc[t, 'workload_outbound'] = sched['workload_outbound']
        df_plan.loc[t, 'labor_inbound'] = sched['labor_inbound']
        df_plan.loc[t, 'labor_outbound'] = sched['labor_outbound']
        df_plan.loc[t, 'amr_active'] = sched['amr_active']
    else:
        # Nếu chưa có trong master schedule nhưng có cam kết Heijunka dời sang
        d_in = st.session_state['committed_heijunka_in'].get(t, 0.0)
        d_out = st.session_state['committed_heijunka_out'].get(t, 0.0)
        if d_in != 0.0:
            df_plan.loc[t, 'workload_inbound'] = max(0.0, df_plan.loc[t, 'workload_inbound'] + d_in)
        if d_out != 0.0:
            df_plan.loc[t, 'workload_outbound'] = max(0.0, df_plan.loc[t, 'workload_outbound'] + d_out)

# 5. Chạy mô phỏng dòng chảy kho: Kế thừa chính xác toàn bộ kế hoạch đã duyệt mà không bị reset
df_sim = capacity_engine.simulate_24h(df_plan, init_stocks)

# Lưu lại trạng thái chuẩn bị bàn giao cho bước sang giờ mới (+1h)
st.session_state['current_executed_state'] = {
    'workload_inbound': float(history_df.loc[current_time, 'workload_inbound']),
    'workload_outbound': float(history_df.loc[current_time, 'workload_outbound']),
    'labor_inbound': int(history_df.loc[current_time, 'labor_inbound']) if 'labor_inbound' in history_df.columns else 3,
    'labor_outbound': int(history_df.loc[current_time, 'labor_outbound']) if 'labor_outbound' in history_df.columns else 3,
    'amr_active': int(history_df.loc[current_time, 'amr_active']) if 'amr_active' in history_df.columns else 4,
    'storage_inbound': float(init_stocks[0]),
    'storage_buffer': float(init_stocks[1]),
    'storage_outbound': float(init_stocks[2])
}

# Tồn kho cuối giờ hiện tại sẽ là khởi điểm của mốc giờ tiếp theo
next_hour_timestamp = current_time + pd.Timedelta(hours=1)
if next_hour_timestamp in df_sim.index:
    st.session_state['current_next_stocks'] = (
        float(df_sim.loc[next_hour_timestamp, 'storage_inbound_sim']),
        float(df_sim.loc[next_hour_timestamp, 'storage_buffer_sim']),
        float(df_sim.loc[next_hour_timestamp, 'storage_outbound_sim'])
    )
else:
    st.session_state['current_next_stocks'] = None

# ==============================================================================
# KHU VỰC CHUYỂN ĐỔI TAB (TOP NAVIGATION BUTTONS)
# ==============================================================================
col_sp_l, col_tab1, col_tab2, col_sp_r = st.columns([1.0, 4.0, 4.0, 1.0])
with col_tab1:
    st.markdown('<div class="top-nav-tabs">', unsafe_allow_html=True)
    is_vh = (st.session_state['active_main_tab'] == "VẬN HÀNH")
    if st.button("VẬN HÀNH", type="primary" if is_vh else "secondary", use_container_width=True, key="btn_nav_van_hanh"):
        st.session_state['active_main_tab'] = "VẬN HÀNH"
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

with col_tab2:
    st.markdown('<div class="top-nav-tabs">', unsafe_allow_html=True)
    is_mp = (st.session_state['active_main_tab'] == "MÔ PHỎNG")
    if st.button("MÔ PHỎNG", type="primary" if is_mp else "secondary", use_container_width=True, key="btn_nav_mo_phong"):
        st.session_state['active_main_tab'] = "MÔ PHỎNG"
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("<div style='margin-bottom: 16px;'></div>", unsafe_allow_html=True)

if st.session_state['active_main_tab'] == "MÔ PHỎNG":
    # TAB MÔ PHỎNG (ĐỂ TRỐNG THEO YÊU CẦU)
    st.markdown("## DEMO VERSION")
    st.caption("Feature currently being updated")
    st.stop()

# ==============================================================================
# HÀNG 1: TÌNH TRẠNG HIỆN TẠI CỦA NHÀ MÁY (FACTORY CURRENT STATUS)
# ==============================================================================
st.markdown("## BẢNG VẬN HÀNH LOGISTICS NHÀ MÁY (CONTROL-ROOM)")
st.caption(f"Mốc thời gian hiện tại: {current_time.strftime('%Y-%m-%d %H:%M')} | Khoảng dự báo: {horizon_option}")

# Banner thông báo khi có các mốc giờ đang vận hành theo kế hoạch điều độ đã duyệt
if active_planned_hours:
    col_ap1, col_ap2 = st.columns([3.8, 1.4])
    with col_ap1:
        st.success(f"✅ **ĐANG VẬN HÀNH THEO KẾ HOẠCH ĐÃ DUYỆT** ({len(active_planned_hours)}/{len(df_plan)} mốc giờ trong horizon đã được điều độ tối ưu, kho an toàn)!")
    with col_ap2:
        st.markdown('<div class="cancel-plan-btn">', unsafe_allow_html=True)
        if st.button("Hủy áp dụng phương án đề xuất", key="btn_cancel_master", use_container_width=True):
            for t in active_planned_hours:
                st.session_state['master_schedule'].pop(t, None)
                st.session_state['committed_heijunka_in'].pop(t, None)
                st.session_state['committed_heijunka_out'].pop(t, None)
            st.session_state['simulated_stocks'] = None
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

cur_w_in = float(history_df['workload_inbound'].iloc[-1])
cur_w_out = float(history_df['workload_outbound'].iloc[-1])
cur_s_in, cur_s_buf, cur_s_out = init_stocks

col_kpi1, col_kpi2, col_kpi3, col_kpi4, col_kpi5 = st.columns(5)

col_kpi1.metric(
    label="Workload Inbound",
    value=f"≈ {round(cur_w_in):.0f} pal/h",
    delta="Đầu vào thực tế"
)

col_kpi2.metric(
    label="Workload Outbound",
    value=f"≈ {round(cur_w_out):.0f} pal/h",
    delta="Đầu ra thực tế"
)

in_pct = (cur_s_in / MAX_STORAGE_INBOUND) * 100
col_kpi3.metric(
    label="Tồn kho Sàn Inbound",
    value=f"≈ {round(cur_s_in):.0f} / {MAX_STORAGE_INBOUND}",
    delta=f"{in_pct:.1f}% sức chứa",
    delta_color="inverse" if cur_s_in >= WARN_STORAGE_INBOUND else "normal"
)

buf_pct = (cur_s_buf / MAX_STORAGE_BUFFER) * 100
col_kpi4.metric(
    label="Tồn kho Kitting Buffer",
    value=f"≈ {round(cur_s_buf):.0f} / {MAX_STORAGE_BUFFER}",
    delta=f"{buf_pct:.1f}% sức chứa",
    delta_color="inverse" if cur_s_buf >= WARN_STORAGE_BUFFER else "normal"
)

out_pct = (cur_s_out / MAX_STORAGE_OUTBOUND) * 100
col_kpi5.metric(
    label="Tồn kho Sàn Outbound",
    value=f"≈ {round(cur_s_out):.0f} / {MAX_STORAGE_OUTBOUND}",
    delta=f"{out_pct:.1f}% sức chứa",
    delta_color="inverse" if cur_s_out >= WARN_STORAGE_OUTBOUND else "normal"
)

st.markdown("---")

# ==============================================================================
# HÀNG 2: 2 BẢNG DỰ BÁO WORKLOAD (INBOUND & OUTBOUND) TRONG KHOẢNG THỜI GIAN t
# ==============================================================================
st.markdown(f"### DỰ BÁO KHỐI LƯỢNG CÔNG VIỆC TRONG {horizon_option} TIẾP THEO")

hint_text_color = "#000000" if is_light else "#ffffff"
st.markdown(f"""
<div style="font-size: 12.5px; margin-bottom: 12px; color: {hint_text_color}; line-height: 1.5; padding: 6px 12px; border-left: 3px solid #0284c7; background: rgba(2, 132, 199, 0.08); border-radius: 4px;">
  <strong>Ý nghĩa chỉ số Tải / Năng lực (%):</strong> So sánh khối lượng công việc đến (pallets/h) với công suất xử lý tối đa của số nhân công/xe trong giờ đó<br>
  <span style="color: #10b981; font-weight: 700;">≤ 100% (An toàn)</span> | 
  <span style="color: #f59e0b; font-weight: 700;">100.1% – 120% (Tải cao - Hàng đệm tạm trên sàn)</span> | 
  <span style="color: #ef4444; font-weight: 800;">&gt; 120% (Quá tải nặng - Nguy cơ tắc nghẽn kho)</span>
</div>
""", unsafe_allow_html=True)

col_w_in, col_w_out = st.columns(2)

connect_time_idx = [history_df.index[-1]] + list(df_sim.index)
connect_w_in = [history_df["workload_inbound"].iloc[-1]] + list(df_sim["workload_inbound"])
connect_w_out = [history_df["workload_outbound"].iloc[-1]] + list(df_sim["workload_outbound"])

# --- BẢNG 1: DỰ BÁO WORKLOAD INBOUND ---
with col_w_in:
    st.markdown("#### Bảng 1: Dự báo Workload Inbound")
    has_heijunka_in = not np.allclose(df_sim["workload_inbound"].values, df_plan_natural["workload_inbound"].values, atol=0.1)
    
    tbl_data_in = {
        "Mốc giờ": [t.strftime("%H:%M %d/%m") for t in df_sim.index],
        "Dự báo AI (pallets/h)": [f"≈ {round(v):.0f}" for v in df_plan_natural["workload_inbound"]],
    }
    if has_heijunka_in:
        tbl_data_in["Kế hoạch dỡ (pallets/h)"] = [f"≈ {round(v):.0f}" for v in df_sim["workload_inbound"]]
    tbl_data_in["Nhân công (người)"] = df_sim["labor_inbound"].astype(int)
    tbl_data_in["Năng lực dỡ (pallets/h)"] = (df_sim["labor_inbound"] * RATE_LABOR_INBOUND).astype(int)
    tbl_data_in["Tải / Năng lực (%)"] = (
        (df_sim["workload_inbound"] / (df_sim["labor_inbound"] * RATE_LABOR_INBOUND)) * 100
    ).round(1)

    tbl_w_in = pd.DataFrame(tbl_data_in)
    st.markdown(render_styled_table(tbl_w_in, is_light_theme=is_light, min_width="540px"), unsafe_allow_html=True)

    if show_charts:
        fig_w_in, ax1 = plt.subplots(figsize=(7, 3.4))
        history_color = "#334155" if is_light else "#64748b"
        forecast_color = "#0284c7" if is_light else "#38bdf8"
        plan_color = "#ea580c" if is_light else "#fb923c"

        connect_w_in_pred = [history_df["workload_inbound"].iloc[-1]] + list(df_plan_natural["workload_inbound"])

        ax1.plot(history_df.index, history_df["workload_inbound"], color=history_color, marker="o", linewidth=2, label="Thực tế (5h trước)")
        ax1.plot(connect_time_idx, connect_w_in_pred, color=forecast_color, linestyle="--", linewidth=2, label=f"Dự báo AI ({horizon_option})")
        ax1.plot(df_sim.index, df_plan_natural["workload_inbound"], color=forecast_color, marker="s", linestyle="None")
        
        if has_heijunka_in:
            ax1.plot(connect_time_idx, connect_w_in, color=plan_color, linestyle="-", linewidth=2, label="Kế hoạch điều độ")
            ax1.plot(df_sim.index, df_sim["workload_inbound"], color=plan_color, marker="^", linestyle="None")

        ax1.axvline(x=current_time, color="gray", linestyle=":", label="Hiện tại")
        ax1.set_ylabel("Pallets/h")
        apply_chart_theme_and_top_legend(fig_w_in, ax1, ncol=4 if has_heijunka_in else 3, is_light_theme=is_light)
        st.pyplot(fig_w_in)
        plt.close(fig_w_in)

# --- BẢNG 2: DỰ BÁO WORKLOAD OUTBOUND ---
with col_w_out:
    st.markdown("#### Bảng 2: Dự báo Workload Outbound")
    has_heijunka_out = not np.allclose(df_sim["workload_outbound"].values, df_plan_natural["workload_outbound"].values, atol=0.1)

    tbl_data_out = {
        "Mốc giờ": [t.strftime("%H:%M %d/%m") for t in df_sim.index],
        "Dự báo AI (pallets/h)": [f"≈ {round(v):.0f}" for v in df_plan_natural["workload_outbound"]],
    }
    if has_heijunka_out:
        tbl_data_out["Kế hoạch xuất (pallets/h)"] = [f"≈ {round(v):.0f}" for v in df_sim["workload_outbound"]]
    tbl_data_out["Nhân công (người)"] = df_sim["labor_outbound"].astype(int)
    tbl_data_out["Số xe AMR"] = df_sim["amr_active"].astype(int)
    tbl_data_out["Năng lực xuất (pallets/h)"] = (df_sim["labor_outbound"] * RATE_LABOR_OUTBOUND).astype(int)
    tbl_data_out["Tải / Năng lực (%)"] = (
        (df_sim["workload_outbound"] / (df_sim["labor_outbound"] * RATE_LABOR_OUTBOUND)) * 100
    ).round(1)

    tbl_w_out = pd.DataFrame(tbl_data_out)
    st.markdown(render_styled_table(tbl_w_out, is_light_theme=is_light, min_width="560px"), unsafe_allow_html=True)

    if show_charts:
        fig_w_out, ax2 = plt.subplots(figsize=(7, 3.4))
        out_forecast_color = "#059669" if is_light else "#34d399"
        plan_color = "#ea580c" if is_light else "#fb923c"

        connect_w_out_pred = [history_df["workload_outbound"].iloc[-1]] + list(df_plan_natural["workload_outbound"])

        ax2.plot(history_df.index, history_df["workload_outbound"], color=history_color, marker="o", linewidth=2, label="Thực tế (5h trước)")
        ax2.plot(connect_time_idx, connect_w_out_pred, color=out_forecast_color, linestyle="--", linewidth=2, label=f"Dự báo AI ({horizon_option})")
        ax2.plot(df_sim.index, df_plan_natural["workload_outbound"], color=out_forecast_color, marker="s", linestyle="None")
        
        if has_heijunka_out:
            ax2.plot(connect_time_idx, connect_w_out, color=plan_color, linestyle="-", linewidth=2, label="Kế hoạch điều độ")
            ax2.plot(df_sim.index, df_sim["workload_outbound"], color=plan_color, marker="^", linestyle="None")

        ax2.axvline(x=current_time, color="gray", linestyle=":", label="Hiện tại")
        ax2.set_ylabel("Pallets/h")
        apply_chart_theme_and_top_legend(fig_w_out, ax2, ncol=4 if has_heijunka_out else 3, is_light_theme=is_light)
        st.pyplot(fig_w_out)
        plt.close(fig_w_out)

st.markdown("---")

# ==============================================================================
# HÀNG 3: 3 BẢNG DỰ BÁO STORAGE (INBOUND, BUFFER, OUTBOUND) TRONG KHOẢNG THỜI GIAN t
# ==============================================================================
st.markdown(f"### DỰ BÁO TÌNH TRẠNG KHO CHỨA TRONG {horizon_option} TIẾP THEO")

col_s_in, col_s_buf, col_s_out = st.columns(3)

def evaluate_status(val, warn, maximum):
    if val >= maximum:
        return "Quá tải"
    elif val >= warn:
        return "Cảnh báo"
    return "An toàn"

connect_s_in = [history_df["storage_inbound"].iloc[-1]] + list(df_sim["storage_inbound_sim"])
connect_s_buf = [history_df["storage_buffer"].iloc[-1]] + list(df_sim["storage_buffer_sim"])
connect_s_out = [history_df["storage_outbound"].iloc[-1]] + list(df_sim["storage_outbound_sim"])

# --- BẢNG 3: STORAGE INBOUND ---
with col_s_in:
    st.markdown("#### Bảng 3: Tồn kho Sàn Inbound")
    tbl_s_in = pd.DataFrame({
        "Mốc giờ": [t.strftime("%H:%M %d/%m") for t in df_sim.index],
        "Tồn kho (pallets)": [f"≈ {round(v):.0f}" for v in df_sim["storage_inbound_sim"]],
        "Cảnh báo (80%)": WARN_STORAGE_INBOUND,
        "Trần chứa": MAX_STORAGE_INBOUND,
        "Đánh giá": [evaluate_status(v, WARN_STORAGE_INBOUND, MAX_STORAGE_INBOUND) for v in df_sim["storage_inbound_sim"]]
    })
    st.markdown(render_styled_table(tbl_s_in, is_light_theme=is_light, min_width="500px"), unsafe_allow_html=True)

    if show_charts:
        fig_s_in, ax3 = plt.subplots(figsize=(5.6, 3.4))
        c_in_hist = "#7c3aed" if is_light else "#a78bfa"
        c_in_sim = "#10b981" if active_planned_hours else ("#9333ea" if is_light else "#c084fc")

        ax3.plot(history_df.index, history_df["storage_inbound"], color=c_in_hist, marker="o", linewidth=2, label="Quá khứ")
        ax3.plot(connect_time_idx, connect_s_in, color=c_in_sim, linestyle="--", linewidth=2, label="Đã điều độ" if active_planned_hours else "Mô phỏng")
        ax3.plot(df_sim.index, df_sim["storage_inbound_sim"], color=c_in_sim, marker="s", linestyle="None")
        ax3.axhline(y=WARN_STORAGE_INBOUND, color="#d97706" if is_light else "#f59e0b", linestyle="--", label=f"Cảnh báo ({WARN_STORAGE_INBOUND:.0f})")
        ax3.axhline(y=MAX_STORAGE_INBOUND, color="#dc2626" if is_light else "#ef4444", linestyle="-", label=f"Trần ({MAX_STORAGE_INBOUND})")
        ax3.set_ylabel("Pallets")
        apply_chart_theme_and_top_legend(fig_s_in, ax3, ncol=4, is_light_theme=is_light)
        st.pyplot(fig_s_in)
        plt.close(fig_s_in)

# --- BẢNG 4: STORAGE BUFFER ---
with col_s_buf:
    st.markdown("#### Bảng 4: Tồn kho Kitting Buffer")
    tbl_s_buf = pd.DataFrame({
        "Mốc giờ": [t.strftime("%H:%M %d/%m") for t in df_sim.index],
        "Tồn kho (khay/thùng)": [f"≈ {round(v):.0f}" for v in df_sim["storage_buffer_sim"]],
        "Cảnh báo (80%)": WARN_STORAGE_BUFFER,
        "Trần chứa": MAX_STORAGE_BUFFER,
        "Đánh giá": [evaluate_status(v, WARN_STORAGE_BUFFER, MAX_STORAGE_BUFFER) for v in df_sim["storage_buffer_sim"]]
    })
    st.markdown(render_styled_table(tbl_s_buf, is_light_theme=is_light, min_width="500px"), unsafe_allow_html=True)

    if show_charts:
        fig_s_buf, ax4 = plt.subplots(figsize=(5.6, 3.4))
        c_buf_hist = "#ea580c" if is_light else "#fb923c"
        c_buf_sim = "#10b981" if active_planned_hours else ("#f97316" if is_light else "#fdba74")

        ax4.plot(history_df.index, history_df["storage_buffer"], color=c_buf_hist, marker="o", linewidth=2, label="Quá khứ")
        ax4.plot(connect_time_idx, connect_s_buf, color=c_buf_sim, linestyle="--", linewidth=2, label="Đã điều độ" if active_planned_hours else "Mô phỏng")
        ax4.plot(df_sim.index, df_sim["storage_buffer_sim"], color=c_buf_sim, marker="s", linestyle="None")
        ax4.axhline(y=WARN_STORAGE_BUFFER, color="#d97706" if is_light else "#f59e0b", linestyle="--", label=f"Cảnh báo ({WARN_STORAGE_BUFFER:.0f})")
        ax4.axhline(y=MAX_STORAGE_BUFFER, color="#dc2626" if is_light else "#ef4444", linestyle="-", label=f"Trần ({MAX_STORAGE_BUFFER})")
        ax4.set_ylabel("Khay/Thùng")
        apply_chart_theme_and_top_legend(fig_s_buf, ax4, ncol=4, is_light_theme=is_light)
        st.pyplot(fig_s_buf)
        plt.close(fig_s_buf)

# --- BẢNG 5: STORAGE OUTBOUND ---
with col_s_out:
    st.markdown("#### Bảng 5: Tồn kho Sàn Outbound")
    tbl_s_out = pd.DataFrame({
        "Mốc giờ": [t.strftime("%H:%M %d/%m") for t in df_sim.index],
        "Tồn kho (pallets)": [f"≈ {round(v):.0f}" for v in df_sim["storage_outbound_sim"]],
        "Cảnh báo (80%)": WARN_STORAGE_OUTBOUND,
        "Trần chứa": MAX_STORAGE_OUTBOUND,
        "Đánh giá": [evaluate_status(v, WARN_STORAGE_OUTBOUND, MAX_STORAGE_OUTBOUND) for v in df_sim["storage_outbound_sim"]]
    })
    st.markdown(render_styled_table(tbl_s_out, is_light_theme=is_light, min_width="500px"), unsafe_allow_html=True)

    if show_charts:
        fig_s_out, ax5 = plt.subplots(figsize=(5.6, 3.4))
        c_out_hist = "#0891b2" if is_light else "#38bdf8"
        c_out_sim = "#10b981" if active_planned_hours else ("#0284c7" if is_light else "#7dd3fc")

        ax5.plot(history_df.index, history_df["storage_outbound"], color=c_out_hist, marker="o", linewidth=2, label="Quá khứ")
        ax5.plot(connect_time_idx, connect_s_out, color=c_out_sim, linestyle="--", linewidth=2, label="Đã điều độ" if active_planned_hours else "Mô phỏng")
        ax5.plot(df_sim.index, df_sim["storage_outbound_sim"], color=c_out_sim, marker="s", linestyle="None")
        ax5.axhline(y=WARN_STORAGE_OUTBOUND, color="#d97706" if is_light else "#f59e0b", linestyle="--", label=f"Cảnh báo ({WARN_STORAGE_OUTBOUND:.0f})")
        ax5.axhline(y=MAX_STORAGE_OUTBOUND, color="#dc2626" if is_light else "#ef4444", linestyle="-", label=f"Trần ({MAX_STORAGE_OUTBOUND})")
        ax5.set_ylabel("Pallets")
        apply_chart_theme_and_top_legend(fig_s_out, ax5, ncol=4, is_light_theme=is_light)
        st.pyplot(fig_s_out)
        plt.close(fig_s_out)

st.markdown("---")

# ==============================================================================
# HÀM POP-UP DIALOG PREVIEW (CÓ NÚT ACCEPT VÀ REJECT ĐỂ ÁP DỤNG TRỰC TIẾP)
# ==============================================================================
@st.dialog("XEM TRƯỚC PHƯƠNG ÁN ĐIỀU CHỈNH (PREVIEW)", width="large")
def show_preview_dialog(df_b, df_a, bottlenecks_orig, plan_solution, horizon_option, is_light_theme, hist_df):
    st.markdown(f"#### ĐÁNH GIÁ HIỆU QUẢ CẢI THIỆN (BEFORE vs AFTER)")
    
    bn_after = capacity_engine.scan_bottlenecks(df_a)
    bn_reduction = len(bottlenecks_orig) - len(bn_after)
    max_in_b, max_in_a = df_b['storage_inbound_sim'].max(), df_a['storage_inbound_sim'].max()
    max_buf_b, max_buf_a = df_b['storage_buffer_sim'].max(), df_a['storage_buffer_sim'].max()
    max_out_b, max_out_a = df_b['storage_outbound_sim'].max(), df_a['storage_outbound_sim'].max()

    r_in_b, r_in_a = int(round(max_in_b)), int(round(max_in_a))
    r_buf_b, r_buf_a = int(round(max_buf_b)), int(round(max_buf_a))
    r_out_b, r_out_a = int(round(max_out_b)), int(round(max_out_a))

    diff_in = r_in_a - r_in_b
    diff_buf = r_buf_a - r_buf_b
    diff_out = r_out_a - r_out_b

    col_met1, col_met2, col_met3, col_met4 = st.columns(4)
    col_met1.metric(
        "Điểm nghẽn kho",
        f"{len(bn_after)} điểm",
        delta=f"Giảm {bn_reduction} điểm" if bn_reduction > 0 else "Đã tối ưu",
        delta_color="normal"
    )
    col_met2.metric(
        "Đỉnh tồn Sàn Inbound",
        f"≈ {r_in_a} pal",
        delta=f"≈ {diff_in:+} pal",
        delta_color="normal" if diff_in <= 0 else "inverse"
    )
    col_met3.metric(
        "Đỉnh tồn Kitting Buffer",
        f"≈ {r_buf_a} khay",
        delta=f"≈ {diff_buf:+} khay",
        delta_color="normal" if diff_buf <= 0 else "inverse"
    )
    col_met4.metric(
        "Đỉnh tồn Sàn Outbound",
        f"≈ {r_out_a} pal",
        delta=f"≈ {diff_out:+} pal",
        delta_color="normal" if diff_out <= 0 else "inverse"
    )

    st.markdown("---")
    st.markdown("##### Biểu đồ so sánh trước và sau điều điều chỉnh")

    prev_conn_time = [hist_df.index[-1]] + list(df_b.index)
    prev_in_b = [hist_df["storage_inbound"].iloc[-1]] + list(df_b["storage_inbound_sim"])
    prev_in_a = [hist_df["storage_inbound"].iloc[-1]] + list(df_a["storage_inbound_sim"])

    prev_buf_b = [hist_df["storage_buffer"].iloc[-1]] + list(df_b["storage_buffer_sim"])
    prev_buf_a = [hist_df["storage_buffer"].iloc[-1]] + list(df_a["storage_buffer_sim"])

    prev_out_b = [hist_df["storage_outbound"].iloc[-1]] + list(df_b["storage_outbound_sim"])
    prev_out_a = [hist_df["storage_outbound"].iloc[-1]] + list(df_a["storage_outbound_sim"])

    col_p_in, col_p_buf, col_p_out = st.columns(3)

    with col_p_in:
        st.markdown("**Sàn Inbound (pallets)**")
        fig_pi, ax_pi = plt.subplots(figsize=(4.6, 2.8))
        orig_color = "#94a3b8" if is_light_theme else "#64748b"
        sol_color_in = "#7c3aed" if is_light_theme else "#a78bfa"

        ax_pi.plot(prev_conn_time, prev_in_b, color=orig_color, linestyle="--", linewidth=1.8, label="Gốc (Trước)")
        ax_pi.plot(prev_conn_time, prev_in_a, color=sol_color_in, marker="o", linewidth=2.2, label="Điều độ (Sau)")
        ax_pi.axhline(y=WARN_STORAGE_INBOUND, color="#d97706" if is_light_theme else "#f59e0b", linestyle=":", label="Cảnh báo")
        ax_pi.axhline(y=MAX_STORAGE_INBOUND, color="#dc2626" if is_light_theme else "#ef4444", linestyle="-", label="Trần")
        ax_pi.set_ylabel("Pallets", fontsize=8)
        apply_chart_theme_and_top_legend(fig_pi, ax_pi, ncol=4, is_light_theme=is_light_theme)
        st.pyplot(fig_pi)
        plt.close(fig_pi)

    with col_p_buf:
        st.markdown("**Kitting Buffer (khay/thùng)**")
        fig_pb, ax_pb = plt.subplots(figsize=(4.6, 2.8))
        sol_color_buf = "#ea580c" if is_light_theme else "#fb923c"

        ax_pb.plot(prev_conn_time, prev_buf_b, color=orig_color, linestyle="--", linewidth=1.8, label="Gốc (Trước)")
        ax_pb.plot(prev_conn_time, prev_buf_a, color=sol_color_buf, marker="o", linewidth=2.2, label="Điều độ (Sau)")
        ax_pb.axhline(y=WARN_STORAGE_BUFFER, color="#d97706" if is_light_theme else "#f59e0b", linestyle=":", label="Cảnh báo")
        ax_pb.axhline(y=MAX_STORAGE_BUFFER, color="#dc2626" if is_light_theme else "#ef4444", linestyle="-", label="Trần")
        ax_pb.set_ylabel("Khay", fontsize=8)
        apply_chart_theme_and_top_legend(fig_pb, ax_pb, ncol=4, is_light_theme=is_light_theme)
        st.pyplot(fig_pb)
        plt.close(fig_pb)

    with col_p_out:
        st.markdown("**Sàn Outbound (pallets)**")
        fig_po, ax_po = plt.subplots(figsize=(4.6, 2.8))
        sol_color_out = "#0284c7" if is_light_theme else "#38bdf8"

        ax_po.plot(prev_conn_time, prev_out_b, color=orig_color, linestyle="--", linewidth=1.8, label="Gốc (Trước)")
        ax_po.plot(prev_conn_time, prev_out_a, color=sol_color_out, marker="o", linewidth=2.2, label="Điều độ (Sau)")
        ax_po.axhline(y=WARN_STORAGE_OUTBOUND, color="#d97706" if is_light_theme else "#f59e0b", linestyle=":", label="Cảnh báo")
        ax_po.axhline(y=MAX_STORAGE_OUTBOUND, color="#dc2626" if is_light_theme else "#ef4444", linestyle="-", label="Trần")
        ax_po.set_ylabel("Pallets", fontsize=8)
        apply_chart_theme_and_top_legend(fig_po, ax_po, ncol=4, is_light_theme=is_light_theme)
        st.pyplot(fig_po)
        plt.close(fig_po)

    st.markdown("---")
    st.markdown("##### Bảng phân tích chi tiết các thay đổi")
    
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
        l_in_b = int(round(df_b.loc[t, "labor_inbound"]))
        l_in_a = int(round(df_a.loc[t, "labor_inbound"]))
        l_out_b = int(round(df_b.loc[t, "labor_outbound"]))
        l_out_a = int(round(df_a.loc[t, "labor_outbound"]))

        rw_in_b, rw_in_a = int(round(w_in_b)), int(round(w_in_a))
        rs_in_b, rs_in_a = int(round(s_in_b)), int(round(s_in_a))
        rs_buf_b, rs_buf_a = int(round(s_buf_b)), int(round(s_buf_a))
        rs_out_b, rs_out_a = int(round(s_out_b)), int(round(s_out_a))

        d_w_in = rw_in_a - rw_in_b
        d_s_in = rs_in_a - rs_in_b
        d_s_buf = rs_buf_a - rs_buf_b
        d_s_out = rs_out_a - rs_out_b

        notes = []
        if l_in_a != l_in_b:
            notes.append(f"Nhân công In: {l_in_b} ➔ {l_in_a}")
        if l_out_a != l_out_b:
            notes.append(f"Nhân công Out: {l_out_b} ➔ {l_out_a}")
        if d_w_in != 0:
            notes.append(f"Workload In dời: ≈ {d_w_in:+} pal")
        if d_s_in < 0:
            notes.append(f"Giảm tồn In ≈ {-d_s_in} pal")
        elif d_s_in > 0:
            notes.append(f"Tăng tồn In ≈ {d_s_in} pal")
        if d_s_buf > 0:
            notes.append(f"Tăng tồn Buffer ≈ {d_s_buf} khay")
        elif d_s_buf < 0:
            notes.append(f"Giảm tồn Buffer ≈ {-d_s_buf} khay")
        if d_s_out > 0:
            notes.append(f"Tăng tồn Outbound ≈ {d_s_out} pal")
        elif d_s_out < 0:
            notes.append(f"Giảm tồn Out ≈ {-d_s_out} pal")

        comparison_rows.append({
            "Mốc giờ": t_str,
            "Workload In (Trước ➔ Sau)": f"≈ {rw_in_b} ➔ ≈ {rw_in_a}",
            "Nhân sự In / Out": f"{l_in_a} / {l_out_a} người",
            "Tồn Inbound (Trước ➔ Sau)": f"≈ {rs_in_b} ➔ ≈ {rs_in_a}",
            "Tồn Buffer (Trước ➔ Sau)": f"≈ {rs_buf_b} ➔ ≈ {rs_buf_a}",
            "Tồn Outbound (Trước ➔ Sau)": f"≈ {rs_out_b} ➔ ≈ {rs_out_a}",
            "Ghi chú cải thiện": "; ".join(notes) if notes else "Ổn định"
        })

    df_comp = pd.DataFrame(comparison_rows)
    st.markdown(render_styled_table(df_comp, is_light_theme=is_light_theme, min_width="780px"), unsafe_allow_html=True)
    
    # --------------------------------------------------------------------------
    # 2 NÚT THỰC THI: CHẤP NHẬN (ACCEPT) HOẶC TỪ CHỐI (REJECT)
    # --------------------------------------------------------------------------
    st.markdown("---")
    st.markdown("##### Bạn có muốn áp dụng phương án đề xuất này vào vận hành không?")
    col_act_yes, col_act_no = st.columns(2)
    
    with col_act_yes:
        if st.button("ÁP DỤNG PHƯƠNG ÁN ĐỀ XUẤT", type="primary", use_container_width=True):
            # 1. Nạp toàn bộ các mốc giờ đã được tối ưu vào Master Schedule bền vững
            for t in df_a.index:
                st.session_state['master_schedule'][t] = {
                    'workload_inbound': float(df_a.loc[t, 'workload_inbound']),
                    'workload_outbound': float(df_a.loc[t, 'workload_outbound']),
                    'labor_inbound': float(df_a.loc[t, 'labor_inbound']),
                    'labor_outbound': float(df_a.loc[t, 'labor_outbound']),
                    'amr_active': float(df_a.loc[t, 'amr_active']),
                    'storage_inbound_sim': float(df_a.loc[t, 'storage_inbound_sim']),
                    'storage_buffer_sim': float(df_a.loc[t, 'storage_buffer_sim']),
                    'storage_outbound_sim': float(df_a.loc[t, 'storage_outbound_sim']),
                }
                # Ghi nhận chênh lệch Heijunka để AI bóc tách sai số tự nhiên khi bước sang giờ mới
                diff_in = float(df_a.loc[t, 'workload_inbound']) - float(df_b.loc[t, 'workload_inbound'])
                diff_out = float(df_a.loc[t, 'workload_outbound']) - float(df_b.loc[t, 'workload_outbound'])
                if diff_in != 0.0:
                    st.session_state['committed_heijunka_in'][t] = st.session_state['committed_heijunka_in'].get(t, 0.0) + diff_in
                if diff_out != 0.0:
                    st.session_state['committed_heijunka_out'][t] = st.session_state['committed_heijunka_out'].get(t, 0.0) + diff_out
            st.rerun()

    with col_act_no:
        if st.button("TỪ CHỐI PHƯƠNG ÁN ĐỀ XUẤT", type="secondary", use_container_width=True):
            st.rerun()

# ==============================================================================
# HÀNG 4: PHÂN TÍCH ĐIỂM NGHẼN & ĐỀ XUẤT ĐIỀU ĐỘ
# ==============================================================================
if run_capacity_solve:
    st.markdown("### PHÂN TÍCH VÀ ĐIỀU CHỈNH NĂNG LỰC VẬN HÀNH")

    bottlenecks_current = capacity_engine.scan_bottlenecks(df_sim)
    unmitigated_bns = [b for b in bottlenecks_current if df_sim.index[b['time_index']] not in active_planned_hours]

    if active_planned_hours and len(active_planned_hours) == len(df_plan) and not unmitigated_bns:
        st.success(f"Trạng thái vận hành ổn định trong {horizon_option} tới. Kế hoạch điều độ tối ưu đã được áp dụng thành công ({len(active_planned_hours)}/{len(df_plan)} mốc giờ), các chỉ số tải và sức chứa kho đều trong ngưỡng an toàn.")
        col_rev1, col_rev2 = st.columns([1.5, 3.5])
        with col_rev1:
            if st.button("Xem lại phương án tối ưu", type="secondary", use_container_width=True, key="btn_review_applied"):
                df_sim_natural = capacity_engine.simulate_24h(df_plan_natural, init_stocks)
                bns_natural = capacity_engine.scan_bottlenecks(df_sim_natural)
                sol_plan = capacity_engine.solve_capacity_bottleneck(df_plan_natural, init_stocks)
                show_preview_dialog(df_sim_natural, df_sim, bns_natural, sol_plan, horizon_option, is_light, history_df)
    elif not bottlenecks_current or not unmitigated_bns:
        st.success(f"Trạng thái vận hành ổn định trong {horizon_option} tới. Không phát hiện điểm nghẽn kho vượt ngưỡng an toàn.")
    else:
        active_bns = unmitigated_bns if active_planned_hours else bottlenecks_current
        st.warning(f"Cảnh báo: Phát hiện {len(active_bns)} mốc thời gian có nguy cơ nghẽn kho trong kế hoạch.")
        bn_rows = []
        for b in active_bns:
            t_idx = b['time_index']
            b_type = b.get('type', '')
            if b_type == 'inbound':
                stock_val = df_sim.iloc[t_idx]['storage_inbound_sim']
                warn_val = WARN_STORAGE_INBOUND
            elif b_type == 'buffer':
                stock_val = df_sim.iloc[t_idx]['storage_buffer_sim']
                warn_val = WARN_STORAGE_BUFFER
            else:
                stock_val = df_sim.iloc[t_idx]['storage_outbound_sim']
                warn_val = WARN_STORAGE_OUTBOUND
            excess = max(0, int(round(stock_val)) - int(round(warn_val)))
            bn_rows.append({
                "Chỉ số bước": b['time_index'],
                "Mốc giờ": b['hour'],
                "Khu vực nghẽn": b['type'],
                "Mức độ vượt ngưỡng (pallets/khay)": f"≈ {excess}"
            })
        df_bn = pd.DataFrame(bn_rows)
        st.markdown(render_styled_table(df_bn, is_light_theme=is_light, min_width="540px"), unsafe_allow_html=True)

        st.markdown("#### Đề xuất phương án điều phối tự động")
        
        # Tìm kiếm giải pháp điều độ cho df_plan hiện tại
        plan_solution = capacity_engine.solve_capacity_bottleneck(df_plan, init_stocks)
        solution_status = plan_solution.get("status", "NO_ACTION_NEEDED")
        df_after_sol = plan_solution.get("df_after", df_sim)

        sol_col1, sol_col2, sol_col3 = st.columns([1.2, 1.8, 1.0])
        
        with sol_col1:
            st.info(f"**Trạng thái:** {solution_status}\n\n**Cấp độ can thiệp:** {plan_solution.get('level', 'N/A')}\n\n**Chi phí nhân công:** {plan_solution.get('cost', 0)} man-hours")

        with sol_col2:
            st.markdown("**Các bước hành động chi tiết:**")
            action_logs = plan_solution.get('action_logs', [])
            if action_logs:
                for log in action_logs:
                    st.write(f"- {format_action_log(log)}")
            else:
                st.write(plan_solution.get('message', 'Không có hành động bổ sung.'))

        with sol_col3:
            st.markdown("**Chế độ xem trước:**")
            if solution_status in ["SUCCESS", "PARTIAL_SUCCESS"]:
                if st.button("Mở chế độ Preview", type="primary", use_container_width=True, key="btn_open_preview"):
                    show_preview_dialog(df_sim, df_after_sol, active_bns, plan_solution, horizon_option, is_light, history_df)
                caption_color = "#000000" if is_light else "#ffffff"
            else:
                st.button("Không khả dụng Preview", disabled=True, use_container_width=True)
