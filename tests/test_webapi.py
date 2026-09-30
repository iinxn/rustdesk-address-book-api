def test_webapi_crud_and_filters(client, user):
    h, guid = user["headers"], user["guid"]

    # customers
    r = client.post("/api/v1/customers", headers=h, json={"name": "Romashka", "note": ""})
    assert r.status_code == 200
    cid = r.json()["id"]

    # entries with tags
    for rid, tags in (("111", ["Red", "Moscow"]), ("222", ["Moscow"]), ("333", [])):
        r = client.post(f"/api/v1/address-books/{guid}/entries", headers=h,
                        json={"rustdesk_id": rid, "alias": rid, "tags": tags, "customer_id": cid})
        assert r.status_code == 200, r.text

    # AND / OR
    r = client.get(f"/api/v1/address-books/{guid}/entries", headers=h, params={"tag": ["Red", "Moscow"], "mode": "and"})
    assert r.json()["total"] == 1
    r = client.get(f"/api/v1/address-books/{guid}/entries", headers=h, params={"tag": ["Red", "Moscow"], "mode": "or"})
    assert r.json()["total"] == 2
    # untagged
    r = client.get(f"/api/v1/address-books/{guid}/entries", headers=h, params={"untagged": "true"})
    assert r.json()["total"] == 1
    # search + pagination
    r = client.get(f"/api/v1/address-books/{guid}/entries", headers=h, params={"search": "111"})
    assert r.json()["total"] == 1
    r = client.get(f"/api/v1/address-books/{guid}/entries", headers=h, params={"page": 2, "page_size": 2})
    assert r.json()["total"] == 3 and len(r.json()["data"]) == 1

    # tags list with usage counts
    r = client.get(f"/api/v1/address-books/{guid}/tags", headers=h)
    counts = {t["name"]: t["devices"] for t in r.json()}
    assert counts == {"Red": 1, "Moscow": 2}

    # duplicate entry prevention
    r = client.post(f"/api/v1/address-books/{guid}/entries", headers=h, json={"rustdesk_id": "111"})
    assert r.status_code == 409

    # attach/detach
    entries = client.get(f"/api/v1/address-books/{guid}/entries", headers=h, params={"search": "333"}).json()["data"]
    eid = entries[0]["id"]
    tag_id = [t for t in client.get(f"/api/v1/address-books/{guid}/tags", headers=h).json() if t["name"] == "Red"][0]["id"]
    assert client.put(f"/api/v1/entries/{eid}/tags/{tag_id}", headers=h).status_code == 200
    assert client.delete(f"/api/v1/entries/{eid}/tags/{tag_id}", headers=h).status_code == 200

    # users admin-only
    r = client.get("/api/v1/users", headers=h)
    assert r.status_code == 200 and any(u["username"] == "tester" for u in r.json())
