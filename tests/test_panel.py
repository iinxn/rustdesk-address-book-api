def test_panel_login_and_pages(client, user):
    r = client.get("/panel/login")
    assert r.status_code == 200 and "Login" in r.text

    r = client.post("/panel/login", data={"username": "tester", "password": "secret123"})
    assert r.status_code in (303, 302, 200), r.text

    for page in ("/panel/devices", "/panel/tags", "/panel/customers", "/panel/users"):
        r = client.get(page)
        assert r.status_code == 200, page


def test_panel_requires_login(client):
    c2 = client
    for page in ("/panel/devices", "/panel/tags"):
        r = c2.get(page, follow_redirects=False)
        assert r.status_code in (303, 307), page
