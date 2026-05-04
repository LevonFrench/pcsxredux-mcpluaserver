"""
PCSX-Redux MCP Server Bridge
Translates MCP JSON-RPC (stdio) to PCSX-Redux REST API (HTTP port 8079).

Usage:
  python pcsx_mcp_bridge.py

This bridge is used by the Antigravity agent to introspect
live PS1 RAM in PCSX-Redux during Toukon 3 recomp development.
"""
import sys
import json
import urllib.request
import urllib.error
import struct

PCSX_BASE = "http://localhost:8079"

def http_get(path):
    """GET request to PCSX-Redux REST API, return bytes."""
    try:
        req = urllib.request.Request(f"{PCSX_BASE}{path}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read()
    except Exception as e:
        raise RuntimeError(f"HTTP GET {path} failed: {e}")

def http_get_json(path):
    """GET request, parse as JSON."""
    data = http_get(path)
    return json.loads(data.decode('utf-8'))

def http_post(path, body=b""):
    """POST request to PCSX-Redux REST API."""
    try:
        req = urllib.request.Request(f"{PCSX_BASE}{path}", data=body, method='POST')
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read()
    except Exception as e:
        raise RuntimeError(f"HTTP POST {path} failed: {e}")

def send_response(obj):
    """Write JSON-RPC response to stdout."""
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()

# --- Tool implementations ---

def tool_get_status():
    info = http_get_json("/api/v1/execution-flow")
    return json.dumps(info, indent=2)

def tool_read_memory(args):
    address = args.get("address", 0)
    size = args.get("size", 16)
    # Convert PS1 virtual address to physical offset
    offset = address & 0x1FFFFF
    ram = http_get("/api/v1/cpu/ram/raw")
    if offset + size > len(ram):
        size = len(ram) - offset
    chunk = ram[offset:offset+size]
    hex_str = " ".join(f"{b:02X}" for b in chunk)
    return f"Memory at 0x{address:08X} ({size} bytes):\n{hex_str}"

def tool_read_u32(args):
    address = args.get("address", 0)
    offset = address & 0x1FFFFF
    ram = http_get("/api/v1/cpu/ram/raw")
    if offset + 4 > len(ram):
        return f"Address 0x{address:08X} out of range"
    val = struct.unpack_from('<I', ram, offset)[0]
    return f"0x{val:08X}"

def tool_read_u16(args):
    address = args.get("address", 0)
    offset = address & 0x1FFFFF
    ram = http_get("/api/v1/cpu/ram/raw")
    if offset + 2 > len(ram):
        return f"Address 0x{address:08X} out of range"
    val = struct.unpack_from('<H', ram, offset)[0]
    return f"0x{val:04X}"

def tool_write_memory(args):
    address = args.get("address", 0)
    hex_data = args.get("hex_data", "")
    offset = address & 0x1FFFFF
    data = bytes.fromhex(hex_data.replace(" ", ""))
    size = len(data)
    http_post(f"/api/v1/cpu/ram/raw?offset={offset}&size={size}", data)
    return f"Wrote {size} bytes to 0x{address:08X}"

def tool_dump_vram():
    vram = http_get("/api/v1/gpu/vram/raw")
    return f"VRAM dump: {len(vram)} bytes (1024x512 16bpp)"

def tool_pause():
    http_post("/api/v1/execution-flow?function=pause&type=shell")
    return "Emulator paused."

def tool_resume():
    http_post("/api/v1/execution-flow?function=resume&type=shell")
    return "Emulator resumed."

TOOLS = [
    {"name": "get_status", "description": "Get emulator execution status (running, debugger, dynarec)", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "read_memory", "description": "Read raw bytes from PS1 RAM at a virtual address", "inputSchema": {"type": "object", "properties": {"address": {"type": "number", "description": "PS1 virtual address (e.g. 0x800BBDEC = 2148990444)"}, "size": {"type": "number", "description": "Number of bytes to read (default 16)"}}, "required": ["address"]}},
    {"name": "read_u32", "description": "Read a 32-bit unsigned integer from PS1 RAM", "inputSchema": {"type": "object", "properties": {"address": {"type": "number", "description": "PS1 virtual address"}}, "required": ["address"]}},
    {"name": "read_u16", "description": "Read a 16-bit unsigned integer from PS1 RAM", "inputSchema": {"type": "object", "properties": {"address": {"type": "number", "description": "PS1 virtual address"}}, "required": ["address"]}},
    {"name": "write_memory", "description": "Write hex bytes to PS1 RAM at a virtual address", "inputSchema": {"type": "object", "properties": {"address": {"type": "number", "description": "PS1 virtual address"}, "hex_data": {"type": "string", "description": "Hex string of bytes to write (e.g. 'FF00')"}}, "required": ["address", "hex_data"]}},
    {"name": "dump_vram", "description": "Dump the entire PS1 VRAM (1024x512 16bpp)", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pause_emulator", "description": "Pause PCSX-Redux emulation", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "resume_emulator", "description": "Resume PCSX-Redux emulation", "inputSchema": {"type": "object", "properties": {}}},
]

def handle_request(req):
    method = req.get("method", "")
    req_id = req.get("id")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "pcsx-redux-mcp", "version": "2.0.0"}
        }}
    elif method == "notifications/initialized":
        return None  # No response for notifications
    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    elif method == "tools/call":
        params = req.get("params", {})
        tool_name = params.get("name", "")
        args = params.get("arguments", {})
        result = {"content": [{"type": "text", "text": "Unknown tool"}]}

        try:
            if tool_name == "get_status":
                text = tool_get_status()
            elif tool_name == "read_memory":
                text = tool_read_memory(args)
            elif tool_name == "read_u32":
                text = tool_read_u32(args)
            elif tool_name == "read_u16":
                text = tool_read_u16(args)
            elif tool_name == "write_memory":
                text = tool_write_memory(args)
            elif tool_name == "dump_vram":
                text = tool_dump_vram()
            elif tool_name == "pause_emulator":
                text = tool_pause()
            elif tool_name == "resume_emulator":
                text = tool_resume()
            else:
                text = f"Unknown tool: {tool_name}"
                result["isError"] = True

            result["content"] = [{"type": "text", "text": text}]
        except Exception as e:
            result["isError"] = True
            result["content"] = [{"type": "text", "text": f"Error: {str(e)}"}]

        return {"jsonrpc": "2.0", "id": req_id, "result": result}
    else:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        resp = handle_request(req)
        if resp is not None:
            send_response(resp)

if __name__ == "__main__":
    main()
