#!/usr/bin/env python3
"""Key fingerprint table (§18). Compares hbbs public key vs client Key.

Usage:
  python3 check_keys.py --hbbs-pub data/id_ed25519.pub --client-key '<Key from client>'
  python3 check_keys.py --hbbs-pub data/id_ed25519.pub   # shows hbbs fingerprint only

Prints SHA256 fingerprints (never private keys). Match => punch stage passes
key check; mismatch => punch fails with LICENSE_MISMATCH (failure=3).
NOTE: key match does NOT fix the logged-in path against OSS hbbs — the
secure_tcp stage fails earlier (server never sends KeyExchange). See
docs/connection-diagnostic.md.
"""
import argparse
import base64
import hashlib


def fpr(b64: str) -> str:
    raw = base64.b64decode(b64.strip())
    return hashlib.sha256(raw).hexdigest()[:32] + f" ({len(raw)} bytes)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hbbs-pub", required=True, help="path to id_ed25519.pub")
    ap.add_argument("--client-key", default="", help="Key string from RustDesk client settings")
    a = ap.parse_args()
    hbbs = open(a.hbbs_pub).read().strip()
    print(f"{'Source':<16} {'SHA256 fingerprint (truncated)'}")
    print(f"{'hbbs':<16} {fpr(hbbs)}")
    if a.client_key:
        print(f"{'client':<16} {fpr(a.client_key)}")
        print("MATCH" if a.client_key.strip() == hbbs else "MISMATCH <- punch stage will fail LICENSE_MISMATCH")
    else:
        print("(pass --client-key to compare; our FastAPI never provides keys)")


if __name__ == "__main__":
    main()
