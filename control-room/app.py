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
# THANH ĐIỀU KHIỂN (SIDEBAR)
# ==============================================================================
st.sidebar.markdown("### BẢNG ĐIỀU KHIỂN")

# Quản lý chế độ hiển thị Dark / Light Mode
theme_choice = st.sidebar.radio(
    "Chế độ giao diện (Theme)",
    options=["🌙 Giao diện Tối (Dark)", "☀️ Giao diện Sáng (Light)"],
    index=0
) 
is_light = "Sáng" in theme_choice

st.sidebar.markdown("---")

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
    "Chọn khoảng thời gian dự báo",
    options=["1h", "3h", "12h"],
    index=1,
    help="Hệ thống chỉ hiển thị duy nhất 1 bộ bảng cho khoảng thời gian t được chọn."
)
horizon_val = int(horizon_option.replace("h", ""))

st.sidebar.markdown("---")
show_charts = st.sidebar.checkbox("Hiển thị biểu đồ trực quan", value=True)
run_capacity_solve = st.sidebar.checkbox("Phân tích điều độ giải phóng nghẽn", value=True)

# ==============================================================================
# HỆ THỐNG GIAO DIỆN & CSS (DARK & LIGHT MODE CHUẨN ĐEN HẲN / TRẮNG HẲN)
# ==============================================================================
if is_light:
    # Cấu hình màu cho chế độ Sáng (Light Mode): Mọi text thông thường dùng ĐEN HẲN (#000000)
    theme_css = """
    <style>
    /* Nền và màu chữ toàn trang */
    .stApp {
        background-color: #f8fafc !important;
        color: #000000 !important;
    }
    header[data-testid="stHeader"] {
        background-color: #f8fafc !important;
    }
    /* Thanh Sidebar */
    [data-testid="stSidebar"] {
        background-color: #ffffff !important;
        border-right: 1.5px solid #cbd5e1 !important;
    }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] span {
        color: #000000 !important;
        font-weight: 600 !important;
    }
    /* Typography */
    h1, h2, h3, h4, h5, h6 {
        color: #000000 !important;
        font-weight: 800 !important;
    }
    p, span, label, div {
        color: #000000;
    }
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
        color: #000000 !important;
        font-weight: 500 !important;
    }
    /* Card KPI Metric: Thu gọn padding và giảm font-size để không bị khuất ... */
    [data-testid="stMetric"] {
        background: #ffffff !important;
        border: 1.5px solid #cbd5e1 !important;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05) !important;
        border-radius: 8px !important;
        padding: 10px 8px !important;
    }
    [data-testid="stMetricLabel"] {
        margin-bottom: 2px !important;
    }
    [data-testid="stMetricLabel"] p {
        color: #000000 !important;
        font-weight: 700 !important;
        font-size: 13px !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }
    [data-testid="stMetricValue"] {
        overflow: visible !important;
    }
    [data-testid="stMetricValue"] > div {
        color: #000000 !important;
        font-weight: 800 !important;
        font-size: 19px !important;
        white-space: nowrap !important;
        overflow: visible !important;
        text-overflow: clip !important;
        line-height: 1.25 !important;
    }
    [data-testid="stMetricDelta"] > div {
        font-size: 11.5px !important;
        white-space: nowrap !important;
        font-weight: 600 !important;
    }
    
    /* Ô CHỌN NGÀY VẬN HÀNH: 1 NÉT BORDER DUY NHẤT, KHÔNG LỖI KHUNG, KHÔNG CHÌA RA */
    [data-testid="stDateInput"] {
        width: 100% !important;
    }
    [data-testid="stDateInput"] div[data-baseweb="input"],
    div[data-baseweb="input"] {
        background-color: #ffffff !important;
        border: 1.5px solid #94a3b8 !important;
        border-radius: 6px !important;
        box-shadow: none !important;
        outline: none !important;
    }
    [data-testid="stDateInput"] div[data-baseweb="base-input"],
    div[data-baseweb="base-input"] {
        background: transparent !important;
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
    }
    [data-testid="stDateInput"] input,
    div[data-baseweb="input"] input {
        background: transparent !important;
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
        color: #000000 !important;
        font-weight: 600 !important;
        font-size: 14px !important;
        padding: 7px 10px !important;
    }
    [data-testid="stDateInput"] svg,
    div[data-baseweb="input"] svg {
        fill: #000000 !important;
        color: #000000 !important;
    }
    div[data-baseweb="calendar"],
    div[data-baseweb="calendar"] * {
        background-color: #ffffff !important;
        color: #000000 !important;
    }
    
    /* NÚT CHỌN MODE (RADIO BUTTONS) TRONG LIGHT MODE: TINH GỌN, KHÔNG BỊ KHỐI XÁM BAO QUANH */
    div[data-testid="stRadio"] [role="radiogroup"] label,
    div[data-testid="stRadio"] label[data-baseweb="radio"] {
        background: transparent !important;
        background-color: transparent !important;
        box-shadow: none !important;
        padding: 3px 4px !important;
        cursor: pointer !important;
    }
    div[data-testid="stRadio"] [role="radiogroup"] label:hover,
    div[data-testid="stRadio"] label[data-baseweb="radio"]:hover {
        background: transparent !important;
        background-color: transparent !important;
    }
    div[data-testid="stRadio"] label p {
        color: #000000 !important;
        font-weight: 600 !important;
    }
    /* Vòng tròn radio button chưa chọn: màu trắng, viền rõ nét */
    div[data-testid="stRadio"] div[data-baseweb="radio"] > div:first-child {
        background-color: #ffffff !important;
        border: 1.5px solid #475569 !important;
        box-shadow: none !important;
    }
    /* Khi được chọn: nền trắng, chấm đỏ */
    div[data-testid="stRadio"] div[data-baseweb="radio"] input:checked + div {
        background-color: #ffffff !important;
        border: 2px solid #ef4444 !important;
        box-shadow: none !important;
    }
    div[data-testid="stRadio"] div[data-baseweb="radio"] input:checked + div > div {
        background-color: #ef4444 !important;
    }
    
    /* Checkbox trong Light Mode */
    div[data-testid="stCheckbox"] label,
    div[data-testid="stCheckbox"] [data-testid="stMarkdownContainer"] p {
        color: #000000 !important;
        font-weight: 600 !important;
    }
    div[data-testid="stCheckbox"] div[data-baseweb="checkbox"] > div:first-child {
        background-color: #ffffff !important;
        border: 2px solid #000000 !important;
    }
    div[data-testid="stCheckbox"] div[data-baseweb="checkbox"] input:checked + div {
        background-color: #ef4444 !important;
        border-color: #ef4444 !important;
    }
    /* Slider trong Light Mode */
    div[data-testid="stSlider"] label,
    div[data-testid="stSlider"] [data-testid="stMarkdownContainer"] p,
    div[data-testid="stSlider"] div[data-baseweb="slider"] div {
        color: #000000 !important;
        font-weight: 600 !important;
    }
    /* Cửa sổ Pop-up Dialog trong Light Mode */
    [data-testid="stDialog"] div[role="dialog"] {
        background-color: #ffffff !important;
        color: #000000 !important;
        border: 2px solid #94a3b8 !important;
        box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.2) !important;
        border-radius: 12px !important;
    }
    [data-testid="stDialog"] div[role="dialog"] * {
        color: #000000 !important;
    }
    [data-testid="stDialog"] button[aria-label="Close"] {
        color: #000000 !important;
    }
    /* Các nút bấm: Nút Primary và Secondary chữ sắc nét */
    [data-testid="stButton"] button[kind="primary"],
    button[data-testid="stBaseButton-primary"] {
        color: #ffffff !important;
        background-color: #ef4444 !important;
        border: none !important;
        font-weight: 700 !important;
    }
    [data-testid="stButton"] button[kind="primary"] * {
        color: #ffffff !important;
        font-weight: 700 !important;
    }
    [data-testid="stButton"] button[kind="secondary"],
    button[data-testid="stBaseButton-secondary"] {
        color: #000000 !important;
        background-color: #ffffff !important;
        border: 1.5px solid #000000 !important;
        font-weight: 700 !important;
    }
    [data-testid="stButton"] button[kind="secondary"] * {
        color: #000000 !important;
        font-weight: 700 !important;
    }
    /* Đường phân cách */
    hr {
        border-color: #cbd5e1 !important;
    }
    /* Thanh cuộn ngang tinh tế cho bảng */
    .styled-table-wrapper {
        scrollbar-width: thin;
        scrollbar-color: #94a3b8 rgba(0, 0, 0, 0.05);
    }
    .styled-table-wrapper::-webkit-scrollbar {
        height: 7px;
    }
    .styled-table-wrapper::-webkit-scrollbar-track {
        background: #f1f5f9;
        border-radius: 4px;
    }
    .styled-table-wrapper::-webkit-scrollbar-thumb {
        background: #94a3b8;
        border-radius: 4px;
    }
    .styled-table-wrapper::-webkit-scrollbar-thumb:hover {
        background: #64748b;
    }
    </style>
    """
else:
    # Cấu hình màu cho chế độ Tối (Dark Mode): Mọi text thông thường dùng TRẮNG HẲN (#ffffff)
    theme_css = """
    <style>
    /* Nền và màu chữ toàn trang */
    .stApp {
        background-color: #0b0f19 !important;
        color: #ffffff !important;
    }
    header[data-testid="stHeader"] {
        background-color: #0b0f19 !important;
    }
    /* Thanh Sidebar */
    [data-testid="stSidebar"] {
        background-color: #111827 !important;
        border-right: 1.5px solid #1f293d !important;
    }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] span {
        color: #ffffff !important;
        font-weight: 600 !important;
    }
    /* Typography */
    h1, h2, h3, h4, h5, h6 {
        color: #ffffff !important;
        font-weight: 800 !important;
    }
    p, span, label, div {
        color: #ffffff;
    }
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
        color: #ffffff !important;
        font-weight: 500 !important;
    }
    /* Card KPI Metric: Thu gọn padding và giảm font-size để không bị khuất ... */
    [data-testid="stMetric"] {
        background: #141c2e !important;
        border: 1.5px solid #233148 !important;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3) !important;
        border-radius: 8px !important;
        padding: 10px 8px !important;
    }
    [data-testid="stMetricLabel"] {
        margin-bottom: 2px !important;
    }
    [data-testid="stMetricLabel"] p {
        color: #ffffff !important;
        font-weight: 700 !important;
        font-size: 13px !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }
    [data-testid="stMetricValue"] {
        overflow: visible !important;
    }
    [data-testid="stMetricValue"] > div {
        color: #ffffff !important;
        font-weight: 800 !important;
        font-size: 19px !important;
        white-space: nowrap !important;
        overflow: visible !important;
        text-overflow: clip !important;
        line-height: 1.25 !important;
    }
    [data-testid="stMetricDelta"] > div {
        font-size: 11.5px !important;
        white-space: nowrap !important;
        font-weight: 600 !important;
    }
    
    /* Ô CHỌN NGÀY VẬN HÀNH TRONG DARK MODE: 1 NÉT BORDER DUY NHẤT */
    [data-testid="stDateInput"] {
        width: 100% !important;
    }
    [data-testid="stDateInput"] div[data-baseweb="input"],
    div[data-baseweb="input"] {
        background-color: #161f30 !important;
        border: 1.5px solid #334155 !important;
        border-radius: 6px !important;
        box-shadow: none !important;
        outline: none !important;
    }
    [data-testid="stDateInput"] div[data-baseweb="base-input"],
    div[data-baseweb="base-input"] {
        background: transparent !important;
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
    }
    [data-testid="stDateInput"] input,
    div[data-baseweb="input"] input {
        background: transparent !important;
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
        color: #ffffff !important;
        font-weight: 600 !important;
        font-size: 14px !important;
        padding: 7px 10px !important;
    }
    [data-testid="stDateInput"] svg,
    div[data-baseweb="input"] svg {
        fill: #ffffff !important;
        color: #ffffff !important;
    }
    div[data-baseweb="calendar"],
    div[data-baseweb="calendar"] * {
        background-color: #111827 !important;
        color: #ffffff !important;
    }
    
    /* Nút chọn Mode (Radio Buttons) trong Dark Mode */
    div[data-testid="stRadio"] [role="radiogroup"] label,
    div[data-testid="stRadio"] label[data-baseweb="radio"] {
        background: transparent !important;
        background-color: transparent !important;
        box-shadow: none !important;
        padding: 3px 4px !important;
        cursor: pointer !important;
    }
    div[data-testid="stRadio"] [role="radiogroup"] label:hover,
    div[data-testid="stRadio"] label[data-baseweb="radio"]:hover {
        background: transparent !important;
        background-color: transparent !important;
    }
    div[data-testid="stRadio"] label p {
        color: #ffffff !important;
        font-weight: 600 !important;
    }
    div[data-testid="stRadio"] div[data-baseweb="radio"] > div:first-child {
        background-color: #111827 !important;
        border: 1.5px solid #94a3b8 !important;
        box-shadow: none !important;
    }
    div[data-testid="stRadio"] div[data-baseweb="radio"] input:checked + div {
        background-color: #111827 !important;
        border: 2px solid #ef4444 !important;
        box-shadow: none !important;
    }
    div[data-testid="stRadio"] div[data-baseweb="radio"] input:checked + div > div {
        background-color: #ef4444 !important;
    }
    
    /* Checkbox trong Dark Mode */
    div[data-testid="stCheckbox"] label,
    div[data-testid="stCheckbox"] [data-testid="stMarkdownContainer"] p {
        color: #ffffff !important;
        font-weight: 600 !important;
    }
    div[data-testid="stCheckbox"] div[data-baseweb="checkbox"] > div:first-child {
        background-color: #111827 !important;
        border: 2px solid #ffffff !important;
    }
    div[data-testid="stCheckbox"] div[data-baseweb="checkbox"] input:checked + div {
        background-color: #ef4444 !important;
        border-color: #ef4444 !important;
    }
    /* Slider trong Dark Mode */
    div[data-testid="stSlider"] label,
    div[data-testid="stSlider"] [data-testid="stMarkdownContainer"] p,
    div[data-testid="stSlider"] div[data-baseweb="slider"] div {
        color: #ffffff !important;
        font-weight: 600 !important;
    }
    /* Cửa sổ Pop-up Dialog trong Dark Mode */
    [data-testid="stDialog"] div[role="dialog"] {
        background-color: #111827 !important;
        color: #ffffff !important;
        border: 2px solid #374151 !important;
        box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.6) !important;
        border-radius: 12px !important;
    }
    [data-testid="stDialog"] div[role="dialog"] * {
        color: #ffffff !important;
    }
    [data-testid="stDialog"] button[aria-label="Close"] {
        color: #ffffff !important;
    }
    /* Các nút bấm: Nút Primary và Secondary chữ trắng hẳn */
    [data-testid="stButton"] button[kind="primary"],
    button[data-testid="stBaseButton-primary"] {
        color: #ffffff !important;
        background-color: #ef4444 !important;
        border: none !important;
        font-weight: 700 !important;
    }
    [data-testid="stButton"] button[kind="primary"] * {
        color: #ffffff !important;
        font-weight: 700 !important;
    }
    [data-testid="stButton"] button[kind="secondary"],
    button[data-testid="stBaseButton-secondary"] {
        color: #ffffff !important;
        background-color: #1e293b !important;
        border: 1.5px solid #ffffff !important;
        font-weight: 700 !important;
    }
    [data-testid="stButton"] button[kind="secondary"] * {
        color: #ffffff !important;
        font-weight: 700 !important;
    }
    /* Đường phân cách */
    hr {
        border-color: #1f293d !important;
    }
    /* Thanh cuộn ngang tinh tế cho bảng */
    .styled-table-wrapper {
        scrollbar-width: thin;
        scrollbar-color: #475569 rgba(255, 255, 255, 0.05);
    }
    .styled-table-wrapper::-webkit-scrollbar {
        height: 7px;
    }
    .styled-table-wrapper::-webkit-scrollbar-track {
        background: #0f172a;
        border-radius: 4px;
    }
    .styled-table-wrapper::-webkit-scrollbar-thumb {
        background: #475569;
        border-radius: 4px;
    }
    .styled-table-wrapper::-webkit-scrollbar-thumb:hover {
        background: #64748b;
    }
    </style>
    """

# CSS bổ sung dùng chung: Ẩn mũi tên stMetricDelta
common_css = """
<style>
[data-testid="stMetricDelta"] svg {
    display: none !important;
}
</style>
"""

st.markdown(theme_css + common_css, unsafe_allow_html=True)

# ==============================================================================
# HÀM HIỂN THỊ BẢNG DỮ LIỆU ĐƯỢC THIẾT KẾ CÓ VIỀN, ĐỘ TƯƠNG PHẢN & THANH CUỘN NGANG
# ==============================================================================
def render_styled_table(df: pd.DataFrame, is_light_theme: bool = False, min_width: str = "540px") -> str:
    """
    Render bảng HTML có đầy đủ viền bao quanh và phân cách từng ô, 
    header tương phản cao, zebra striping xen kẽ và thanh cuộn ngang (horizontal scroll) mượt mà.
    Chữ đen hẳn trong Light Mode, trắng hẳn trong Dark Mode.
    Đồng thời phân cấp màu sắc Tải / Năng lực (%) khoa học và chuẩn xác.
    """
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
            
            # Format nội dung cell và badge trạng thái
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
                    # PHÂN CẤP Ý NGHĨA KHOA HỌC:
                    # > 120%: Quá tải nặng -> Màu đỏ (Nguy cơ nghẽn kho nghiêm trọng)
                    # 100.1% - 120%: Tải cao -> Màu vàng cam (Vượt nhẹ công suất, hàng đệm tạm trên sàn)
                    # <= 100%: An toàn -> Màu xanh lá (Công suất đáp ứng tốt)
                    if pct_val > 120.0:
                        cell_content = f'<span style="color: #ef4444; font-weight: 800;" title="Quá tải nặng (&gt; 120%): Khối lượng công việc vượt xa công suất nhân lực!">{val}%</span>'
                    elif pct_val > 100.0:
                        cell_content = f'<span style="color: #f59e0b; font-weight: 700;" title="Tải cao (100% - 120%): Vượt nhẹ công suất tức thời, hàng sẽ tích lũy trên sàn kho">{val}%</span>'
                    else:
                        cell_content = f'<span style="color: #10b981; font-weight: 600;" title="An toàn (≤ 100%): Nhân lực đủ khả năng xử lý">{val}%</span>'
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

# ==============================================================================
# HÀM ĐỊNH DẠNG BIỂU ĐỒ MATPLOTLIB (CHÚ THÍCH NGANG PHÍA TRÊN & THEME)
# ==============================================================================
def apply_chart_theme_and_top_legend(fig, ax, ncol: int = 4, is_light_theme: bool = False):
    """
    Thiết lập giao diện biểu đồ ăn khớp với Dark/Light Mode và tạo khoảng trống ngang,
    nhỏ ở phía trên để bố trí chú thích (legend) ngang, hoàn toàn không bị đè vào đồ thị.
    Chữ đen hẳn trong Light Mode, trắng hẳn trong Dark Mode.
    """
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

    # Đặt chú thích nằm ngang ở dải trên cùng ngoài trục vẽ
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
    # Tinh chỉnh margin phía trên để tạo khoảng trống nhỏ cho legend
    fig.subplots_adjust(top=0.83, bottom=0.22, left=0.13, right=0.96)
    fig.autofmt_xdate(rotation=30, ha="right")

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

# Trang chính luôn hiển thị kế hoạch gốc đang vận hành để đảm bảo tính ổn định
df_sim = df_sim_original

# ==============================================================================
# HÀNG 1: TÌNH TRẠNG HIỆN TẠI CỦA NHÀ MÁY (FACTORY CURRENT STATUS)
# ==============================================================================
st.markdown("## BẢNG VẬN HÀNH LOGISTICS NHÀ MÁY (CONTROL-ROOM)")
st.caption(f"Mốc thời gian hiện tại: {current_time.strftime('%Y-%m-%d %H:%M')} | Khoảng dự báo: {horizon_option}")

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

col_kpi1, col_kpi2, col_kpi3, col_kpi4, col_kpi5 = st.columns(5)

# Workload Inbound
col_kpi1.metric(
    label="Workload Inbound",
    value=f"≈ {round(cur_w_in):.0f} pal/h",
    delta=f"Nhân công: {cur_l_in} người"
)

# Workload Outbound
col_kpi2.metric(
    label="Workload Outbound",
    value=f"≈ {round(cur_w_out):.0f} pal/h",
    delta=f"Nhân công: {cur_l_out} | AMR: {cur_amr}"
)

# Storage Inbound
in_pct = (cur_s_in / MAX_STORAGE_INBOUND) * 100
col_kpi3.metric(
    label="Tồn kho Sàn Inbound",
    value=f"≈ {round(cur_s_in):.0f} / {MAX_STORAGE_INBOUND}",
    delta=f"{in_pct:.1f}% sức chứa",
    delta_color="inverse" if cur_s_in >= WARN_STORAGE_INBOUND else "normal"
)

# Storage Buffer
buf_pct = (cur_s_buf / MAX_STORAGE_BUFFER) * 100
col_kpi4.metric(
    label="Tồn kho Kitting Buffer",
    value=f"≈ {round(cur_s_buf):.0f} / {MAX_STORAGE_BUFFER}",
    delta=f"{buf_pct:.1f}% sức chứa",
    delta_color="inverse" if cur_s_buf >= WARN_STORAGE_BUFFER else "normal"
)

# Storage Outbound
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
st.markdown(f"### DỰ BÁO KHỐI LƯỢNG CÔNG VIỆC TRONG {horizon_option} TỚI")

# Dòng giải thích ý nghĩa chỉ số Tải / Năng lực trực quan, khoa học
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
    tbl_w_in = pd.DataFrame({
        "Mốc giờ": [t.strftime("%H:%M %d/%m") for t in df_sim.index],
        "Dự báo (pallets/h)": [f"≈ {round(v):.0f}" for v in df_sim["workload_inbound"]],
        "Nhân công (người)": df_sim["labor_inbound"].astype(int),
        "Năng lực dỡ (pallets/h)": (df_sim["labor_inbound"] * RATE_LABOR_INBOUND).astype(int),
    })
    tbl_w_in["Tải / Năng lực (%)"] = (
        (df_sim["workload_inbound"] / (df_sim["labor_inbound"] * RATE_LABOR_INBOUND)) * 100
    ).round(1)
    
    st.markdown(render_styled_table(tbl_w_in, is_light_theme=is_light, min_width="540px"), unsafe_allow_html=True)

    if show_charts:
        fig_w_in, ax1 = plt.subplots(figsize=(7, 3.4))
        history_color = "#334155" if is_light else "#64748b"
        forecast_color = "#0284c7" if is_light else "#38bdf8"

        ax1.plot(
            history_df.index,
            history_df["workload_inbound"],
            color=history_color,
            marker="o",
            linewidth=2,
            label="Thực tế (5h trước)"
        )
        ax1.plot(
            connect_time_idx,
            connect_w_in,
            color=forecast_color,
            linestyle="--",
            linewidth=2,
            label=f"Dự báo {horizon_option}"
        )
        ax1.plot(
            df_sim.index,
            df_sim["workload_inbound"],
            color=forecast_color,
            marker="s",
            linestyle="None"
        )
        ax1.axvline(x=current_time, color="gray", linestyle=":", label="Hiện tại")
        ax1.set_ylabel("Pallets/h")
        apply_chart_theme_and_top_legend(fig_w_in, ax1, ncol=3, is_light_theme=is_light)
        st.pyplot(fig_w_in)
        plt.close(fig_w_in)

# --- BẢNG 2: DỰ BÁO WORKLOAD OUTBOUND ---
with col_w_out:
    st.markdown("#### Bảng 2: Dự báo Workload Outbound")
    tbl_w_out = pd.DataFrame({
        "Mốc giờ": [t.strftime("%H:%M %d/%m") for t in df_sim.index],
        "Dự báo (pallets/h)": [f"≈ {round(v):.0f}" for v in df_sim["workload_outbound"]],
        "Nhân công (người)": df_sim["labor_outbound"].astype(int),
        "Số xe AMR": df_sim["amr_active"].astype(int),
        "Năng lực xuất (pallets/h)": (df_sim["labor_outbound"] * RATE_LABOR_OUTBOUND).astype(int),
    })
    tbl_w_out["Tải / Năng lực (%)"] = (
        (df_sim["workload_outbound"] / (df_sim["labor_outbound"] * RATE_LABOR_OUTBOUND)) * 100
    ).round(1)
    
    st.markdown(render_styled_table(tbl_w_out, is_light_theme=is_light, min_width="560px"), unsafe_allow_html=True)

    if show_charts:
        fig_w_out, ax2 = plt.subplots(figsize=(7, 3.4))
        out_forecast_color = "#059669" if is_light else "#34d399"

        ax2.plot(
            history_df.index,
            history_df["workload_outbound"],
            color=history_color,
            marker="o",
            linewidth=2,
            label="Thực tế (5h trước)"
        )
        ax2.plot(
            connect_time_idx,
            connect_w_out,
            color=out_forecast_color,
            linestyle="--",
            linewidth=2,
            label=f"Dự báo {horizon_option}"
        )
        ax2.plot(
            df_sim.index,
            df_sim["workload_outbound"],
            color=out_forecast_color,
            marker="s",
            linestyle="None"
        )
        ax2.axvline(x=current_time, color="gray", linestyle=":", label="Hiện tại")
        ax2.set_ylabel("Pallets/h")
        apply_chart_theme_and_top_legend(fig_w_out, ax2, ncol=3, is_light_theme=is_light)
        st.pyplot(fig_w_out)
        plt.close(fig_w_out)

st.markdown("---")

# ==============================================================================
# HÀNG 3: 3 BẢNG DỰ BÁO STORAGE (INBOUND, BUFFER, OUTBOUND) TRONG KHOẢNG THỜI GIAN t
# ==============================================================================
st.markdown(f"### MÔ PHỎNG DÒNG CHẢY VÀ SỨC CHỨA KHO TRONG {horizon_option} TỚI")

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
        c_in_sim = "#9333ea" if is_light else "#c084fc"

        ax3.plot(history_df.index, history_df["storage_inbound"], color=c_in_hist, marker="o", linewidth=2, label="Quá khứ")
        ax3.plot(connect_time_idx, connect_s_in, color=c_in_sim, linestyle="--", linewidth=2, label="Mô phỏng")
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
        c_buf_sim = "#f97316" if is_light else "#fdba74"

        ax4.plot(history_df.index, history_df["storage_buffer"], color=c_buf_hist, marker="o", linewidth=2, label="Quá khứ")
        ax4.plot(connect_time_idx, connect_s_buf, color=c_buf_sim, linestyle="--", linewidth=2, label="Mô phỏng")
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
        c_out_sim = "#0284c7" if is_light else "#7dd3fc"

        ax5.plot(history_df.index, history_df["storage_outbound"], color=c_out_hist, marker="o", linewidth=2, label="Quá khứ")
        ax5.plot(connect_time_idx, connect_s_out, color=c_out_sim, linestyle="--", linewidth=2, label="Mô phỏng")
        ax5.plot(df_sim.index, df_sim["storage_outbound_sim"], color=c_out_sim, marker="s", linestyle="None")
        ax5.axhline(y=WARN_STORAGE_OUTBOUND, color="#d97706" if is_light else "#f59e0b", linestyle="--", label=f"Cảnh báo ({WARN_STORAGE_OUTBOUND:.0f})")
        ax5.axhline(y=MAX_STORAGE_OUTBOUND, color="#dc2626" if is_light else "#ef4444", linestyle="-", label=f"Trần ({MAX_STORAGE_OUTBOUND})")
        ax5.set_ylabel("Pallets")
        apply_chart_theme_and_top_legend(fig_s_out, ax5, ncol=4, is_light_theme=is_light)
        st.pyplot(fig_s_out)
        plt.close(fig_s_out)

st.markdown("---")

# ==============================================================================
# HÀM POP-UP DIALOG PREVIEW (MODAL CÓ DẤU X Ở GÓC, VẼ BIỂU ĐỒ 3 STORAGE SO SÁNH TRỰC QUAN)
# ==============================================================================
@st.dialog("XEM TRƯỚC PHƯƠNG ÁN ĐIỀU ĐỘ (PREVIEW)", width="large")
def show_preview_dialog(df_b, df_a, bottlenecks_orig, plan_solution, horizon_option, is_light_theme, hist_df):
    st.markdown(f"#### ĐÁNH GIÁ HIỆU QUẢ CẢI THIỆN (BEFORE vs AFTER) TRONG {horizon_option}")
    
    bn_after = capacity_engine.scan_bottlenecks(df_a)
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
        delta=f"Giảm {bn_reduction} điểm" if bn_reduction > 0 else "Đã tối ưu",
        delta_color="normal"
    )
    col_met2.metric(
        "Đỉnh tồn Sàn Inbound",
        f"≈ {round(max_in_a):.0f} pal",
        delta=f"≈ {round(diff_in):+.0f} pal",
        delta_color="normal" if diff_in <= 0 else "inverse"
    )
    col_met3.metric(
        "Đỉnh tồn Kitting Buffer",
        f"≈ {round(max_buf_a):.0f} khay",
        delta=f"≈ {round(diff_buf):+.0f} khay",
        delta_color="normal" if diff_buf <= 0 else "inverse"
    )
    col_met4.metric(
        "Đỉnh tồn Sàn Outbound",
        f"≈ {round(max_out_a):.0f} pal",
        delta=f"≈ {round(diff_out):+.0f} pal",
        delta_color="normal" if diff_out <= 0 else "inverse"
    )

    # --------------------------------------------------------------------------
    # VẼ LẠI BIỂU ĐỒ LINE CHART CỦA 3 STORAGE SAU KHI ÁP DỤNG PHƯƠNG ÁN (SO SÁNH TRƯỚC / SAU)
    # --------------------------------------------------------------------------
    st.markdown("---")
    st.markdown("##### Biểu đồ so sánh tồn kho 3 khu vực: Trước (Kế hoạch gốc) vs Sau điều phối")

    prev_conn_time = [hist_df.index[-1]] + list(df_b.index)
    prev_in_b = [hist_df["storage_inbound"].iloc[-1]] + list(df_b["storage_inbound_sim"])
    prev_in_a = [hist_df["storage_inbound"].iloc[-1]] + list(df_a["storage_inbound_sim"])

    prev_buf_b = [hist_df["storage_buffer"].iloc[-1]] + list(df_b["storage_buffer_sim"])
    prev_buf_a = [hist_df["storage_buffer"].iloc[-1]] + list(df_a["storage_buffer_sim"])

    prev_out_b = [hist_df["storage_outbound"].iloc[-1]] + list(df_b["storage_outbound_sim"])
    prev_out_a = [hist_df["storage_outbound"].iloc[-1]] + list(df_a["storage_outbound_sim"])

    col_p_in, col_p_buf, col_p_out = st.columns(3)

    # Biểu đồ Sàn Inbound trong Popup
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

    # Biểu đồ Kitting Buffer trong Popup
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

    # Biểu đồ Sàn Outbound trong Popup
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
    st.markdown("##### Bảng phân tích so sánh chi tiết từng mốc giờ (Delta Analysis)")
    
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
        l_in_a = int(df_a.loc[t, "labor_inbound"])
        l_out_a = int(df_a.loc[t, "labor_outbound"])

        notes = []
        if int(df_a.loc[t, "labor_inbound"]) != int(df_b.loc[t, "labor_inbound"]):
            notes.append(f"Nhân công In: {int(df_b.loc[t, 'labor_inbound'])} ➔ {l_in_a}")
        if int(df_a.loc[t, "labor_outbound"]) != int(df_b.loc[t, "labor_outbound"]):
            notes.append(f"Nhân công Out: {int(df_b.loc[t, 'labor_outbound'])} ➔ {l_out_a}")
        if round(w_in_a) != round(w_in_b):
            notes.append(f"Workload In dời: ≈ {round(w_in_a - w_in_b):+.0f}")
        if round(s_in_a) < round(s_in_b):
            notes.append(f"Giảm tồn In ≈ {round(s_in_b - s_in_a):.0f} pal")
        if round(s_buf_a) > round(s_buf_b):
            notes.append(f"Tăng tồn Buffer ≈ {round(s_buf_a - s_buf_b):.0f} khay")
        elif round(s_buf_a) < round(s_buf_b):
            notes.append(f"Giảm tồn Buffer ≈ {round(s_buf_b - s_buf_a):.0f} khay")
        if round(s_out_a) > round(s_out_b):
            notes.append(f"Tăng tồn Outbound ≈ {round(s_out_a - s_out_b):.0f} pal")
        elif round(s_out_a) < round(s_out_b):
            notes.append(f"Giảm tồn Out ≈ {round(s_out_b - s_out_a):.0f} pal")

        comparison_rows.append({
            "Mốc giờ": t_str,
            "Workload In (Trước ➔ Sau)": f"≈ {round(w_in_b):.0f} ➔ ≈ {round(w_in_a):.0f}",
            "Nhân sự In / Out": f"{l_in_a} / {l_out_a} người",
            "Tồn Inbound (Trước ➔ Sau)": f"≈ {round(s_in_b):.0f} ➔ ≈ {round(s_in_a):.0f}",
            "Tồn Buffer (Trước ➔ Sau)": f"≈ {round(s_buf_b):.0f} ➔ ≈ {round(s_buf_a):.0f}",
            "Tồn Outbound (Trước ➔ Sau)": f"≈ {round(s_out_b):.0f} ➔ ≈ {round(s_out_a):.0f}",
            "Ghi chú cải thiện": "; ".join(notes) if notes else "Ổn định"
        })

    df_comp = pd.DataFrame(comparison_rows)
    # Bảng phân tích 7 cột nên đặt min_width 780px để cuộn ngang mượt mà
    st.markdown(render_styled_table(df_comp, is_light_theme=is_light_theme, min_width="780px"), unsafe_allow_html=True)
    
    hint_color = "#000000" if is_light_theme else "#ffffff"
    # st.markdown(f"<p style='color: {hint_color}; font-size: 13px; font-weight: 600; margin-top: 10px;'>💡 Quý điều hành có thể đóng cửa sổ xem trước bằng dấu ✖ ở góc phải trên hoặc nút Đóng bên dưới.</p>", unsafe_allow_html=True)
    if st.button("Đóng cửa sổ Preview", type="secondary", use_container_width=True):
        st.rerun()

# ==============================================================================
# HÀNG 4: PHÂN TÍCH ĐIỂM NGHẼN & ĐỀ XUẤT ĐIỀU ĐỘ
# ==============================================================================
if run_capacity_solve:
    st.markdown("### PHÂN TÍCH VÀ ĐIỀU ĐỘ NĂNG LỰC (CAPACITY OPTIMIZATION)")
    bottlenecks_orig = capacity_engine.scan_bottlenecks(df_sim_original)

    if not bottlenecks_orig:
        st.success(f"Trạng thái vận hành ổn định trong {horizon_option} tới. Không phát hiện điểm nghẽn kho vượt ngưỡng an toàn.")
    else:
        st.warning(f"Cảnh báo: Phát hiện {len(bottlenecks_orig)} mốc thời gian có nguy cơ nghẽn kho trong kế hoạch gốc.")
        
        # Bảng chi tiết các điểm nghẽn gốc được thiết kế viền rõ nét và có thể kéo ngang
        df_bn = pd.DataFrame(bottlenecks_orig)
        df_bn.columns = ["Chỉ số bước", "Mốc giờ", "Khu vực nghẽn", "Mức độ vượt ngưỡng (pallets/khay)"]
        df_bn["Mức độ vượt ngưỡng (pallets/khay)"] = [f"≈ {round(float(v)):.0f}" for v in df_bn["Mức độ vượt ngưỡng (pallets/khay)"]]
        st.markdown(render_styled_table(df_bn, is_light_theme=is_light, min_width="540px"), unsafe_allow_html=True)

        st.markdown("#### Đề xuất phương án điều phối tự động")
        
        sol_col1, sol_col2, sol_col3 = st.columns([1.2, 1.8, 1.0])
        
        with sol_col1:
            st.info(f"**Trạng thái:** {solution_status}\n\n**Cấp độ can thiệp:** {plan_solution.get('level', 'N/A')}\n\n**Chi phí nhân công:** {plan_solution.get('cost', 0)} man-hours")

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
                if st.button("Mở chế độ Preview", type="primary", use_container_width=True):
                    show_preview_dialog(df_sim_original, df_after_sol, bottlenecks_orig, plan_solution, horizon_option, is_light, history_df)
                caption_color = "#000000" if is_light else "#ffffff"
                st.markdown(f"<p style='color: {caption_color}; font-size: 12.5px; font-weight: 500; margin-top: 6px;'>Xem dự báo và dòng chảy kho sau khi áp dụng phương án trong cửa sổ pop-up.</p>", unsafe_allow_html=True)
            else:
                st.button("Không khả dụng Preview", disabled=True, use_container_width=True)
