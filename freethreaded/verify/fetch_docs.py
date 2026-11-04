"""Download the real-world test PDFs listed in freethreaded/testdocs/manifest.json.

usage: python fetch_docs.py MANIFEST OUTDIR

All are public domain, CC0 or CC BY (see the manifest for each file's licence, evidence and
attribution); they are downloaded, not stored in the repository. Pinned files must match their
sha256. A few URLs always serve the current edition ("pinned": false): a changed hash is only
reported. A failed download is reported and skipped; fewer than 90% of the files is an error.
"""
import hashlib, json, os, sys, time, urllib.request

manifest, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
docs = json.load(open(manifest))
ok = 0
for d in docs:
    path = os.path.join(out, d["name"])
    if not os.path.exists(path):
        for attempt in range(3):
            try:
                req = urllib.request.Request(d["url"], headers={"User-Agent": "pymupdf-315t-ci/1.0"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = r.read()
                break
            except Exception as e:
                print(f"{d['name']}: download failed ({e})", flush=True)
                data = None
                time.sleep(5 * (attempt + 1))
        if data is None:
            continue
        if not data.startswith(b"%PDF"):
            print(f"{d['name']}: not a PDF, skipped", flush=True)
            continue
        with open(path + ".part", "wb") as f:
            f.write(data)
        os.replace(path + ".part", path)
    digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
    if digest != d["sha256"]:
        if d.get("pinned", True):
            print(f"{d['name']}: sha256 mismatch, removed", flush=True)
            os.remove(path)
            continue
        print(f"{d['name']}: unpinned, sha256 changed to {digest}", flush=True)
    ok += 1
print(f"fetched {ok}/{len(docs)}")
sys.exit(0 if ok >= 0.9 * len(docs) else 1)
