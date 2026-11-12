from app import create_app, socketio

app = create_app()

if __name__ == "__main__":
    # host 0.0.0.0 để điện thoại cùng Wi-Fi quét QR vào được
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
