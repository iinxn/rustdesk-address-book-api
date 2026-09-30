"""Real /api/ab/* flows exactly as the Flutter client calls them."""


def test_full_rustdesk_flow(client, user):
    h, guid = user["headers"], user["guid"]

    r = client.post("/api/ab/settings", headers=h)
    assert r.status_code == 200 and "max_peer_one_ab" in r.json()

    r = client.post("/api/ab/shared/profiles?current=1&pageSize=100", headers=h)
    assert r.status_code == 200 and r.json()["total"] == 0

    # add peer like AbModel.addIdToCurrent
    r = client.post(f"/api/ab/peer/add/{guid}", headers=h,
                    json={"id": "123456789", "alias": "Kacca 1", "tags": [], "note": "shop"})
    assert r.status_code == 200, r.text

    # duplicate prevention
    r = client.post(f"/api/ab/peer/add/{guid}", headers=h, json={"id": "123456789", "alias": "x", "tags": []})
    assert r.status_code == 409 and "error" in r.json()

    r = client.post(f"/api/ab/peers?current=1&pageSize=100&ab={guid}", headers=h)
    assert r.status_code == 200
    assert r.json()["total"] == 1 and r.json()["data"][0]["alias"] == "Kacca 1"

    # tags CRUD
    r = client.post(f"/api/ab/tag/add/{guid}", headers=h, json={"name": "Red", "color": 1})
    assert r.status_code == 200
    r = client.post(f"/api/ab/tag/add/{guid}", headers=h, json={"name": "Moscow", "color": 2})
    assert r.status_code == 200

    # assign full tag list (sync semantics)
    r = client.put(f"/api/ab/peer/update/{guid}", headers=h, json={"id": "123456789", "tags": ["Red", "Moscow"]})
    assert r.status_code == 200
    r = client.post(f"/api/ab/peers?current=1&pageSize=100&ab={guid}", headers=h)
    assert sorted(r.json()["data"][0]["tags"]) == ["Moscow", "Red"]

    # shrink list -> unlink Moscow
    r = client.put(f"/api/ab/peer/update/{guid}", headers=h, json={"id": "123456789", "tags": ["Red"]})
    assert r.status_code == 200
    r = client.post(f"/api/ab/peers?current=1&pageSize=100&ab={guid}", headers=h)
    assert r.json()["data"][0]["tags"] == ["Red"]

    # rename + color
    r = client.put(f"/api/ab/tag/rename/{guid}", headers=h, json={"old": "Red", "new": "Krasny"})
    assert r.status_code == 200
    r = client.put(f"/api/ab/tag/update/{guid}", headers=h, json={"name": "Krasny", "color": 99})
    assert r.status_code == 200
    r = client.post(f"/api/ab/tags/{guid}", headers=h)
    assert r.json() == [{"name": "Krasny", "color": 99}, {"name": "Moscow", "color": 2}]

    # alias via dedicated update
    r = client.put(f"/api/ab/peer/update/{guid}", headers=h, json={"id": "123456789", "alias": "POS-01"})
    assert r.status_code == 200

    # delete tag removes only tag+links
    r = client.request("DELETE", f"/api/ab/tag/{guid}", headers=h, json=["Moscow"])
    assert r.status_code == 200, r.text
    r = client.post(f"/api/ab/peers?current=1&pageSize=100&ab={guid}", headers=h)
    assert r.json()["total"] == 1  # device survives

    # delete peer
    r = client.request("DELETE", f"/api/ab/peer/{guid}", headers=h, json=["123456789"])
    assert r.status_code == 200
    r = client.post(f"/api/ab/peers?current=1&pageSize=100&ab={guid}", headers=h)
    assert r.json()["total"] == 0


def test_legacy_and_group_stubs(client, user):
    h = user["headers"]
    assert client.get("/api/ab", headers=h).text == "null"
    assert client.post("/api/ab", headers=h).status_code == 200
    assert client.get("/api/login-options").json() == []
    for url in ("/api/users?current=1&pageSize=100", "/api/peers?current=1&pageSize=100",
                "/api/device-group/accessible?current=1&pageSize=100"):
        r = client.get(url, headers=h)
        assert r.json() == {"total": 0, "data": []}, url
