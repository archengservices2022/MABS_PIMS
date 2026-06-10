import requests, re
from bs4 import BeautifulSoup

BASE = "http://127.0.0.1:5000"
s = requests.Session()
r = s.post(f"{BASE}/login", data={"email": "kotasridhar17@gmail.com", "password": "123456"})
assert "/login" not in r.url, "login failed"
print("Logged in OK\n")

ids = ["-OubnqK_4Rzti-u_bMne", "-Ouc4t0ettWQXml2VM1w"]
for pid in ids:
    for path in (f"/projects/{pid}", f"/projects/{pid}/edit"):
        rr = s.get(BASE + path)
        plan = "Payment Plan" in rr.text
        fin = "Financial Summary" in rr.text or "Payment Plan" in rr.text
        print(f"{path:40s} -> {rr.status_code}  PaymentPlanCard/Section={plan}")
        if rr.status_code != 200:
            print("   !! non-200")

# Invoice list -> open first invoice detail
r = s.get(f"{BASE}/invoicing")
soup = BeautifulSoup(r.text, "html.parser")
inv_links = list(dict.fromkeys(a["href"] for a in soup.select("a[href*='/invoicing/']") if re.search(r"/invoicing/[^/]+$", a.get("href",""))))
print(f"\nFound {len(inv_links)} invoice links, sample:", inv_links[:3])
for href in inv_links[:3]:
    rr = s.get(BASE + href)
    print(f"{href} -> {rr.status_code}  ({len(rr.text)} bytes)  ProjectInfo={'info-label\">Project' in rr.text or 'Shared across' in rr.text}")
