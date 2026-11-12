from flask_login import current_user
from flask_socketio import join_room

from . import socketio

STAFF_ROOMS = {"kitchen", "waiter", "cashier"}


@socketio.on("join")
def on_join(data):
    room = (data or {}).get("room", "")
    if room in STAFF_ROOMS:
        if current_user.is_authenticated:
            join_room(room)
    elif room.startswith("session-"):      # khách theo dõi đơn của bàn mình
        join_room(room)
