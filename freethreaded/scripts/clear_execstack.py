"""Clear the executable-stack flag of every shared object in a wheel; write it with a build tag.

usage: python -I clear_execstack.py WHEEL OUTDIR [BUILD]

For every ELF .so whose PT_GNU_STACK segment has PF_X, clears that one bit (what
`patchelf --clear-execstack` and linking with -z noexecstack produce), then updates those files'
RECORD lines, adds `Build: BUILD` (default 1) to the dist-info WHEEL file and writes
OUTDIR/<name>-<version>-<BUILD>-<tags>.whl. Every other member is copied byte for byte, in the same
order with the same zip metadata. Prints what it changed. Standard library only.

glibc >= 2.41 refuses to dlopen a .so that asks for an executable stack; see
freethreaded/verify/check_execstack.py.
"""

import base64
import hashlib
import os
import struct
import sys
import zipfile

PT_GNU_STACK = 0x6474E551
PF_X = 1


def clear_execstack(data):
    """Return (new bytes, offset of the changed p_flags) or (data, None) if nothing to clear."""
    if data[:4] != b"\x7fELF":
        return data, None
    is64 = data[4] == 2
    end = "<" if data[5] == 1 else ">"
    if is64:
        e_phoff, = struct.unpack_from(end + "Q", data, 0x20)
        e_phentsize, e_phnum = struct.unpack_from(end + "HH", data, 0x36)
    else:
        e_phoff, = struct.unpack_from(end + "I", data, 0x1C)
        e_phentsize, e_phnum = struct.unpack_from(end + "HH", data, 0x2A)
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type, = struct.unpack_from(end + "I", data, off)
        if p_type != PT_GNU_STACK:
            continue
        flags_off = off + (4 if is64 else 24)
        p_flags, = struct.unpack_from(end + "I", data, flags_off)
        if not p_flags & PF_X:
            return data, None
        out = bytearray(data)
        struct.pack_into(end + "I", out, flags_off, p_flags & ~PF_X)
        return bytes(out), flags_off
    return data, None


def record_hash(data):
    digest = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def main(wheel, outdir, build="1"):
    base = os.path.basename(wheel)
    parts = base[:-len(".whl")].split("-")
    if len(parts) != 5:
        sys.exit(f"{base}: expected name-version-py-abi-plat.whl without a build tag")
    if not build[:1].isdigit():
        sys.exit("a build tag must start with a digit")
    name, version, py, abi, plat = parts
    out_name = f"{name}-{version}-{build}-{py}-{abi}-{plat}.whl"
    dist_info = f"{name}-{version}.dist-info/"

    with zipfile.ZipFile(wheel) as zin:
        infos = zin.infolist()
        contents = {i.filename: zin.read(i) for i in infos}

    changed = {}
    for fn, data in contents.items():
        b = fn.rsplit("/", 1)[-1]
        if not (b.endswith(".so") or ".so." in b):
            continue
        new, off = clear_execstack(data)
        if off is not None:
            changed[fn] = new
            print(f"cleared PF_X in PT_GNU_STACK: {fn} (p_flags at file offset {off:#x})")
    if not changed:
        print("no shared object asks for an executable stack; nothing written")
        return 0

    wheel_fn = dist_info + "WHEEL"
    lines = contents[wheel_fn].decode().splitlines(keepends=True)
    if any(l.startswith("Build:") for l in lines):
        sys.exit(f"{wheel_fn} already has a Build line")
    nl = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    # After the Generator/Root-Is-Purelib header lines, before the Tag lines.
    at = next((i for i, l in enumerate(lines) if l.startswith("Tag:")), len(lines))
    lines.insert(at, f"Build: {build}{nl}")
    changed[wheel_fn] = "".join(lines).encode()
    print(f"added 'Build: {build}' to {wheel_fn}")

    record_fn = dist_info + "RECORD"
    rec_text = contents[record_fn].decode()
    rec_nl = "\r\n" if "\r\n" in rec_text else "\n"
    out_lines = []
    updated = set()
    for line in rec_text.splitlines():
        path = line.rsplit(",", 2)[0] if line.count(",") >= 2 else None
        if path in changed:
            line = f"{path},{record_hash(changed[path])},{len(changed[path])}"
            updated.add(path)
        out_lines.append(line)
    missing = set(changed) - updated
    if missing:
        sys.exit(f"RECORD has no line for {sorted(missing)}")
    changed[record_fn] = (rec_nl.join(out_lines) + (rec_nl if rec_text.endswith(("\n", "\r\n")) else "")).encode()
    print(f"updated {record_fn}: {', '.join(sorted(updated))}")

    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, out_name)
    with zipfile.ZipFile(out, "w") as zout:
        for info in infos:
            data = changed.get(info.filename, contents[info.filename])
            zout.writestr(info, data, compress_type=info.compress_type)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    sys.exit(main(*sys.argv[1:]))
