"""Sort ThreadSanitizer reports into races in our code and noise from the interpreter.
The interpreter is not built with TSan, so its own synchronisation (mimalloc, atomics, the
queue the thread pool uses) is invisible and shows up as races inside python3.15t. A report
counts as ours when the first non-interceptor frame of either access is outside python3.15t
(MuPDF, the bindings, layout extensions).
usage: python tsan_triage.py TSAN_LOG... ; exits 1 if any report is ours."""
import collections, re, sys

INTERCEPTOR = re.compile(r"libtsan\.so|sanitizer_common|/bits/string")
# Reviewed false positives: (frame of one access, frame of the other), and why.
REVIEWED = [
    # A wrapper reads its own fresh argument tuple; the "previous write" is PyTuple_New on
    # memory that mimalloc recycled from another thread, a hand-off TSan cannot see.
    ("SWIG_Python_UnpackTuple", "PyTuple_New"),
]


def first_frame(access):
    for line in access.splitlines():
        if re.match(r"\s*#\d+ ", line) and not INTERCEPTOR.search(line):
            return line.strip()
    return ""


ours, noise = collections.Counter(), 0
for path in sys.argv[1:]:
    for rep in open(path, errors="replace").read().split("WARNING: ThreadSanitizer:")[1:]:
        body = re.split(r"\n\s*(?:Location is|Mutex |Thread T\d+ )", rep)[0]
        accesses = re.split(r"\n\s*Previous ", body)[:2]
        frames = [first_frame(a) for a in accesses]
        if all("(python3.15t+" in f for f in frames if f) or any(
                all(any(name in f for f in frames) for name in pair) for pair in REVIEWED):
            noise += 1
            continue
        key = " || ".join(re.sub(r"\s*\(\S+\+0x[0-9a-f]+\).*", "", re.sub(r"^#\d+ ", "", f)) for f in frames)
        ours[key] += 1
print(f"tsan: {sum(ours.values())} reports in our code, {noise} in the interpreter or reviewed (ignored)")
for key, n in ours.most_common():
    print(f"  {n:4d}  {key}")
sys.exit(1 if ours else 0)
