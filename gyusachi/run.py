import os

from app import create_app, socketio
from app.scheduler import start_scheduler

app = create_app()

if __name__ == "__main__":
    # Chế độ debug chạy 2 tiến trình (reloader); chỉ tiến trình con mới chạy bộ lập lịch sao lưu.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_scheduler(app)
    # host 0.0.0.0 để điện thoại cùng Wi-Fi quét QR vào được
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
