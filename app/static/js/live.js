// Thông báo nhỏ + vào "phòng" SocketIO để nhận sự kiện realtime (KH4.2, BEP1.1, PV...)
function toast(msg) {
  const box = document.getElementById("toasts");
  if (!box) return;
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => el.remove(), 10000);
}

function joinRoom(room, handlers) {
  if (typeof io === "undefined") return null;
  const socket = io();
  socket.on("connect", () => socket.emit("join", { room }));
  Object.entries(handlers || {}).forEach(([event, fn]) => socket.on(event, fn));
  return socket;
}

async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  let data = {};
  try { data = await r.json(); } catch (e) { /* trả về không phải JSON */ }
  return { ok: r.ok, data };
}
