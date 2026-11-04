"""Sort ThreadSanitizer reports into races in our code and noise from uninstrumented code.
With the sanitizer runtime preloaded, the interpreter, onnxruntime and numpy are not built
with TSan, so their own synchronisation (mimalloc, atomics, the thread pools' queues) is
invisible and shows up as races inside them. A report counts as ours when the first
non-interceptor frame of either access is in our code (MuPDF, the bindings, layout
extensions). The tsan-python CI job runs an instrumented interpreter, where nothing in
CPython needs ignoring.
usage: python tsan_triage.py TSAN_LOG... ; exits 1 if any report is ours."""
import collections, re, sys

INTERCEPTOR = re.compile(r"libtsan\.so|sanitizer_common|/bits/string")
# Modules not built with TSan, by the name in the frame's "(module+0x...)".
UNINSTRUMENTED = {"python3.15t": "interpreter", "onnxruntime_pybind11_state.so": "onnxruntime",
                  "_multiarray_umath.": "numpy", "_umath_linalg.": "numpy"}


def module_of(frame):
    for name, label in UNINSTRUMENTED.items():
        if "(" + name in frame:
            return label
    return None
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


ours, noise = collections.Counter(), collections.Counter()
for path in sys.argv[1:]:
    for rep in open(path, errors="replace").read().split("WARNING: ThreadSanitizer:")[1:]:
        body = re.split(r"\n\s*(?:Location is|Mutex |Thread T\d+ )", rep)[0]
        accesses = re.split(r"\n\s*Previous ", body)[:2]
        frames = [first_frame(a) for a in accesses]
        frames = [f for f in frames if f]
        mods = [module_of(f) for f in frames]
        if frames and all(mods):
            noise[" + ".join(sorted(set(mods)))] += 1
            continue
        if any(all(any(name in f for f in frames) for name in pair) for pair in REVIEWED):
            noise["reviewed"] += 1
            continue
        key = " || ".join(re.sub(r"\s*\(\S+\+0x[0-9a-f]+\).*", "", re.sub(r"^#\d+ ", "", f)) for f in frames)
        ours[key] += 1
print(f"tsan: {sum(ours.values())} reports in our code; ignored: "
      + (", ".join(f"{n} in {k}" for k, n in noise.most_common()) or "none"))
for key, n in ours.most_common():
    print(f"  {n:4d}  {key}")
sys.exit(1 if ours else 0)
