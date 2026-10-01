"""
Entry point thuận tiện để khởi chạy Control Room Streamlit từ thư mục gốc:
Lệnh chạy: streamlit run app.py
Hoặc: streamlit run control-room/app.py
"""
import runpy
from pathlib import Path

control_room_path = Path(__file__).resolve().parent / "control-room" / "app.py"
runpy.run_path(str(control_room_path), run_name="__main__")
 