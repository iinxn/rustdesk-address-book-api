"""rustdesk_id validation: IDs with server-redirect characters must be rejected.

Background: the client's LoginConfigHandler treats "id@server?key=..." as a
different-server directive and trailing "/r" as force-relay
(client.rs:1811-1846). Such an entry would connect elsewhere while the bare
ID typed manually works — an AB-only connection-path divergence.
"""
from app.core.validators import validate_rustdesk_id


def test_valid_ids():
    assert validate_rustdesk_id("123456789") is None
    assert validate_rustdesk_id("abc-DEF_012.3") is None


def test_redirect_chars_rejected():
    for bad in ("1@evil.example.com", "1@evil?key=AAA", "123/r", "12/34",
                "a\\b", "a?b", "a&b", "a=b", "12 34", ""):
        assert validate_rustdesk_id(bad) is not None, bad


def test_api_rejects_redirect_id(client, user):
    h, guid = user["headers"], user["guid"]
    r = client.post(f"/api/ab/peer/add/{guid}", headers=h,
                    json={"id": "123@evil.example.com", "alias": "x", "tags": []})
    assert r.status_code == 422
    assert "error" in r.json()
    r = client.post("/api/v1/address-books/%s/entries" % guid, headers=h,
                    json={"rustdesk_id": "123/r"})
    assert r.status_code == 422
