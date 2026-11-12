"""Luồng khách quét QR (qua giao diện HTTP)."""
from datetime import datetime

from app import db
from helpers import dish, open_table, table


def url(code, tail=""):
    return f"/t/{table(code).qr_token}{tail}"


def test_unknown_token_is_404(client):
    assert client.get("/t/khong-co-ban-nay").status_code == 404


def test_message_when_table_not_opened(client):
    r = client.get(url("B03"))
    assert r.status_code == 200 and "chờ nhân viên" in r.get_data(as_text=True)


def test_message_when_restaurant_closed(client, clock):
    open_table("B03")
    clock.t = datetime(2026, 11, 11, 15, 0)                    # giữa hai ca
    assert "chưa mở cửa" in client.get(url("B03")).get_data(as_text=True)


def test_locked_table_is_refused(client):
    table("B04").is_locked = True
    db.session.commit()
    assert client.get(url("B04")).status_code == 403


def test_customer_flow(client):
    open_table("B03", tier=1)
    r = client.get(url("B03"))
    assert r.status_code == 200 and "Bàn B03" in r.get_data(as_text=True)

    ok = client.post(url("B03", "/order"), json={"items": [{"id": dish("Trà đá").id, "qty": 2}]})
    assert ok.status_code == 200 and ok.get_json()["order_id"]

    too_many = client.post(url("B03", "/order"), json={"items": [{"id": dish("Trà đá").id, "qty": 99}]})
    assert too_many.status_code == 400 and "từ 1 đến" in too_many.get_json()["error"]

    assert client.post(url("B03", "/order"), json={"items": []}).status_code == 400


def test_menu_page_hides_dishes_above_the_package(client):
    open_table("B01", tier=1)
    open_table("B02", tier=6)
    assert "Bò Wagyu A5" not in client.get(url("B01", "/menu")).get_data(as_text=True)
    assert "Bò Wagyu A5" in client.get(url("B02", "/menu")).get_data(as_text=True)


def test_customer_can_call_staff_and_request_cancel(client, clock):
    from helpers import place
    sess = open_table("B03")
    assert client.post(url("B03", "/call-staff")).status_code == 200
    item = place(sess, ("Trà đá", 1)).items[0]
    assert client.post(url("B03", f"/cancel/{item.id}"), json={"reason": "đổi ý"}).status_code == 200
    clock.advance(minutes=10)
    item2 = place(sess, ("Kim chi", 1)).items[0]
    clock.advance(minutes=10)
    r = client.post(url("B03", f"/cancel/{item2.id}"), json={"reason": "muộn"})
    assert r.status_code == 400
