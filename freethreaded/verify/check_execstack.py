"""Fail if any ELF shared object in a wheel asks for an executable stack.

usage: python -I check_execstack.py WHEEL [WHEEL ...]

glibc 2.41 and later refuse to dlopen a shared object whose PT_GNU_STACK segment is RWE
("cannot enable executable stack as shared object requires"), so such a wheel cannot be
imported on Debian trixie. A missing PT_GNU_STACK counts as executable too (the old default).
Prints one line per .so: flags and path. Exit status 1 if any is RWE or missing.
Standard library only; reads the ELF program headers directly.
"""

import struct
import sys
import zipfile

PT_GNU_STACK = 0x6474E551
PF_X, PF_W, PF_R = 1, 2, 4


def gnu_stack_flags(data):
    """Return 'RW', 'RWE', ... for PT_GNU_STACK, or None if the segment is missing."""
    if data[:4] != b"\x7fELF":
        raise ValueError("not an ELF file")
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
        p_flags, = struct.unpack_from(end + "I", data, off + (4 if is64 else 24))
        return ("R" if p_flags & PF_R else "") + ("W" if p_flags & PF_W else "") + ("E" if p_flags & PF_X else "")
    return None


def main(wheels):
    bad = 0
    seen = 0
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as zf:
            for name in sorted(zf.namelist()):
                base = name.rsplit("/", 1)[-1]
                if not (base.endswith(".so") or ".so." in base):
                    continue
                data = zf.read(name)
                if data[:4] != b"\x7fELF":
                    continue
                seen += 1
                flags = gnu_stack_flags(data)
                shown = flags or "missing"
                ok = flags is not None and "E" not in flags
                bad += not ok
                print(f"{shown:8} {'ok ' if ok else 'BAD'} {wheel}:{name}")
    if not seen:
        print("no ELF shared objects found", file=sys.stderr)
        return 1
    if bad:
        print(f"{bad} shared object(s) need an executable stack; glibc >= 2.41 will refuse to load them",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1:]))
