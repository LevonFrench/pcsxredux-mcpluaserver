"""
pcsx_cmd.py — PCSX-Redux Remote Control CLI

Direct command-line access to emulator state via the built-in REST API (port 8079).
Zero dependencies beyond Python 3 standard library.

Usage:
  python pcsx_cmd.py status                      # Emulator status
  python pcsx_cmd.py read <addr> [size]           # Read bytes (hex dump)
  python pcsx_cmd.py u32 <addr>                   # Read uint32
  python pcsx_cmd.py u16 <addr>                   # Read uint16
  python pcsx_cmd.py write <addr> <hex_bytes>     # Write bytes
  python pcsx_cmd.py scan <addr> <size> <hex>     # Find hex pattern in range
  python pcsx_cmd.py watch <addr> [size] [interval] # Poll address continuously
  python pcsx_cmd.py pause                        # Pause emulation
  python pcsx_cmd.py resume                       # Resume emulation
  python pcsx_cmd.py vram [outfile]               # Dump VRAM to file
  python pcsx_cmd.py diff <addr> <size>           # Snapshot + diff on next call
  python pcsx_cmd.py press <button> [frames]       # Press button via Lua pad override
  python pcsx_cmd.py release                       # Release all pad overrides
  python pcsx_cmd.py screenshot [outfile]          # Capture framebuffer as PNG
  python pcsx_cmd.py ss [outfile]                  # Alias for screenshot

Buttons: start, cross, circle, triangle, square, up, down, left, right, l1, l2, r1, r2, select
Address format: hex with or without 0x prefix (e.g. 800BBDEC or 0x800BBDEC)
"""
import sys
import struct
import urllib.request
import urllib.error
import json
import time
import os

# --- Configuration ---
BASE = os.environ.get("PCSX_API_URL", "http://localhost:8079")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DIFF_FILE = os.path.join(SCRIPT_DIR, ".ram_snapshot.bin")
PAD_CMD_FILE = os.path.join(SCRIPT_DIR, "pad_cmd.txt")
SS_DIR = os.path.join(SCRIPT_DIR, "screenshots")

# --- HTTP helpers ---

def http_get(path, timeout=5):
    try:
        req = urllib.request.Request(f"{BASE}{path}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        print(f"ERROR: HTTP GET {path} failed: {e}", file=sys.stderr)
        sys.exit(1)

def http_get_json(path, timeout=5):
    return json.loads(http_get(path, timeout).decode('utf-8'))

def http_post(path, body=b"", timeout=5):
    try:
        req = urllib.request.Request(f"{BASE}{path}", data=body, method='POST')
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        print(f"ERROR: HTTP POST {path} failed: {e}", file=sys.stderr)
        sys.exit(1)

def get_ram():
    return http_get("/api/v1/cpu/ram/raw", timeout=10)

def parse_addr(s):
    """Parse hex address, strip 0x prefix, return physical offset and virtual address."""
    s = s.strip().replace("0x", "").replace("0X", "")
    virt = int(s, 16)
    phys = virt & 0x1FFFFF
    return phys, virt

def hex_dump(data, base_addr, width=16):
    """Pretty hex dump with ASCII."""
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i+width]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"  {base_addr + i:08X}  {hex_part:<{width*3}}  |{ascii_part}|")
    return "\n".join(lines)

# --- Commands ---

def cmd_status():
    try:
        info = http_get_json("/api/v1/execution-flow", timeout=3)
    except SystemExit:
        info = {"error": "timeout (emulator may be busy)"}
    print(json.dumps(info, indent=2))

def cmd_read(addr_str, size_str="16"):
    phys, virt = parse_addr(addr_str)
    size = int(size_str)
    ram = get_ram()
    end = min(phys + size, len(ram))
    chunk = ram[phys:end]
    print(f"Memory at 0x{virt:08X} ({end - phys} bytes):")
    print(hex_dump(chunk, virt))

def cmd_u32(addr_str):
    phys, virt = parse_addr(addr_str)
    ram = get_ram()
    val = struct.unpack_from('<I', ram, phys)[0]
    print(f"[0x{virt:08X}] = 0x{val:08X} ({val})")

def cmd_u16(addr_str):
    phys, virt = parse_addr(addr_str)
    ram = get_ram()
    val = struct.unpack_from('<H', ram, phys)[0]
    print(f"[0x{virt:08X}] = 0x{val:04X} ({val})")

def cmd_write(addr_str, hex_data):
    phys, virt = parse_addr(addr_str)
    data = bytes.fromhex(hex_data.replace(" ", ""))
    http_post(f"/api/v1/cpu/ram/raw?offset={phys}&size={len(data)}", data)
    print(f"Wrote {len(data)} bytes to 0x{virt:08X}: {hex_data}")

def cmd_scan(addr_str, size_str, pattern_hex):
    phys, virt = parse_addr(addr_str)
    size = int(size_str)
    pattern = bytes.fromhex(pattern_hex.replace(" ", ""))
    ram = get_ram()
    region = ram[phys:phys+size]
    matches = []
    idx = 0
    while idx < len(region):
        pos = region.find(pattern, idx)
        if pos == -1:
            break
        matches.append(virt + pos)
        idx = pos + 1
    if matches:
        print(f"Found {len(matches)} match(es) for '{pattern_hex}':")
        for m in matches:
            print(f"  0x{m:08X}")
    else:
        print(f"No matches for '{pattern_hex}' in range 0x{virt:08X}+{size}")

def cmd_watch(addr_str, size_str="4", interval_str="0.5"):
    phys, virt = parse_addr(addr_str)
    size = int(size_str)
    interval = float(interval_str)
    prev = None
    print(f"Watching 0x{virt:08X} ({size} bytes), interval={interval}s. Ctrl+C to stop.")
    try:
        while True:
            ram = get_ram()
            chunk = ram[phys:phys+size]
            if chunk != prev:
                ts = time.strftime("%H:%M:%S")
                if size <= 4:
                    if size == 4:
                        val = struct.unpack_from('<I', chunk, 0)[0]
                        print(f"[{ts}] 0x{virt:08X} = 0x{val:08X}")
                    elif size == 2:
                        val = struct.unpack_from('<H', chunk, 0)[0]
                        print(f"[{ts}] 0x{virt:08X} = 0x{val:04X}")
                    else:
                        print(f"[{ts}] 0x{virt:08X} = {' '.join(f'{b:02X}' for b in chunk)}")
                else:
                    print(f"[{ts}] 0x{virt:08X} changed:")
                    print(hex_dump(chunk, virt))
                prev = chunk
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")

def cmd_pause():
    http_post("/api/v1/execution-flow?function=pause&type=shell")
    print("Emulator paused.")

def cmd_resume():
    http_post("/api/v1/execution-flow?function=resume&type=shell")
    print("Emulator resumed.")

def cmd_vram(outfile=None):
    vram = http_get("/api/v1/gpu/vram/raw", timeout=10)
    if outfile:
        with open(outfile, 'wb') as f:
            f.write(vram)
        print(f"VRAM dumped to {outfile} ({len(vram)} bytes)")
    else:
        print(f"VRAM: {len(vram)} bytes (1024x512 16bpp = {1024*512*2} expected)")

def cmd_diff(addr_str, size_str):
    phys, virt = parse_addr(addr_str)
    size = int(size_str)
    ram = get_ram()
    chunk = ram[phys:phys+size]

    if os.path.exists(DIFF_FILE):
        with open(DIFF_FILE, 'rb') as f:
            meta = f.read(8)
            old_phys, old_size = struct.unpack('<II', meta)
            old_chunk = f.read(old_size)
        os.remove(DIFF_FILE)

        if old_phys == phys and old_size == size:
            diffs = []
            for i in range(size):
                if old_chunk[i] != chunk[i]:
                    diffs.append((i, old_chunk[i], chunk[i]))
            if diffs:
                print(f"Changes at 0x{virt:08X} ({len(diffs)} bytes differ):")
                for off, old, new in diffs[:50]:
                    print(f"  +0x{off:04X} (0x{virt+off:08X}): {old:02X} -> {new:02X}")
                if len(diffs) > 50:
                    print(f"  ... and {len(diffs)-50} more")
            else:
                print("No changes.")
        else:
            print("Snapshot address/size mismatch. Taking new snapshot.")
            with open(DIFF_FILE, 'wb') as f:
                f.write(struct.pack('<II', phys, size))
                f.write(chunk)
            print(f"Snapshot saved ({size} bytes at 0x{virt:08X})")
    else:
        with open(DIFF_FILE, 'wb') as f:
            f.write(struct.pack('<II', phys, size))
            f.write(chunk)
        print(f"Snapshot saved ({size} bytes at 0x{virt:08X}). Run again to diff.")

def cmd_press(btn, frames_str="15"):
    """Press a button via Lua file-based IPC (requires pad_control.lua loaded)."""
    frames = int(frames_str)
    with open(PAD_CMD_FILE, 'w') as f:
        f.write(f"{btn} {frames}")
    print(f"Pressed {btn} for {frames} frames")

def cmd_release():
    """Release all pad overrides."""
    with open(PAD_CMD_FILE, 'w') as f:
        f.write("release")
    print("Released all buttons")

# --- Screenshot (pure Python PNG, no PIL) ---

def _png_chunk(ctype, data):
    import zlib as _zlib
    c = ctype + data
    return struct.pack('>I', len(data)) + c + struct.pack('>I', _zlib.crc32(c) & 0xffffffff)

def vram_to_png(vram_data, outfile, x=0, y=0, w=320, h=240):
    """Convert a region of 16bpp VRAM (RGB555) to a PNG file. Pure Python."""
    import zlib as _zlib
    raw_data = bytearray()
    vram_w = 1024
    for row in range(h):
        raw_data.append(0)  # PNG filter byte = None
        for col in range(w):
            src_off = ((y + row) * vram_w + (x + col)) * 2
            if src_off + 1 < len(vram_data):
                val = struct.unpack_from('<H', vram_data, src_off)[0]
                raw_data.append((val & 0x1F) << 3)
                raw_data.append(((val >> 5) & 0x1F) << 3)
                raw_data.append(((val >> 10) & 0x1F) << 3)
            else:
                raw_data.extend(b'\x00\x00\x00')

    with open(outfile, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        f.write(_png_chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)))
        f.write(_png_chunk(b'IDAT', _zlib.compress(bytes(raw_data))))
        f.write(_png_chunk(b'IEND', b''))

def cmd_screenshot(outfile=None):
    """Capture the visible framebuffer from VRAM as a PNG."""
    vram = http_get("/api/v1/gpu/vram/raw", timeout=10)
    if not outfile:
        os.makedirs(SS_DIR, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        outfile = os.path.join(SS_DIR, f"ss_{ts}.png")
    vram_to_png(vram, outfile, x=0, y=0, w=320, h=240)
    print(f"Screenshot: {outfile}")
    return outfile

# --- Main ---

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()
    args = sys.argv[2:]

    commands = {
        "status": (cmd_status, 0, 0),
        "read": (cmd_read, 1, 2),
        "u32": (cmd_u32, 1, 1),
        "u16": (cmd_u16, 1, 1),
        "write": (cmd_write, 2, 2),
        "scan": (cmd_scan, 3, 3),
        "watch": (cmd_watch, 1, 3),
        "pause": (cmd_pause, 0, 0),
        "resume": (cmd_resume, 0, 0),
        "vram": (cmd_vram, 0, 1),
        "diff": (cmd_diff, 2, 2),
        "press": (cmd_press, 1, 2),
        "release": (cmd_release, 0, 0),
        "screenshot": (cmd_screenshot, 0, 1),
        "ss": (cmd_screenshot, 0, 1),
    }

    if cmd not in commands:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)

    func, min_args, max_args = commands[cmd]
    if len(args) < min_args or len(args) > max_args:
        print(f"Wrong number of arguments for '{cmd}'")
        print(__doc__)
        sys.exit(1)

    func(*args)

if __name__ == "__main__":
    main()
