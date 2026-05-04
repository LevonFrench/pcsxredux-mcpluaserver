# pcsx-redux-rc

**Remote Control toolkit for PCSX-Redux** — command-line memory introspection, pad input injection, and VRAM screenshots for PS1 reverse engineering.

Works with any PS1 game running in PCSX-Redux. Zero dependencies beyond Python 3.

## Architecture

```
                     ┌─ REST API (port 8079) ─── RAM read/write, VRAM, execution control
pcsx_cmd.py ────────┤
                     └─ File IPC (pad_cmd.txt) ── pad_control.lua (VSync listener) ── Hardware pad override
```

### Two Communication Channels

1. **REST API (port 8079)** — Memory read/write, VRAM dumps, pause/resume. Uses the native PCSX-Redux C++ web server. Zero Lua dependency.
2. **Lua File IPC** — Pad button control. A Lua VSync listener (`pad_control.lua`) polls `pad_cmd.txt` every frame and applies hardware-level pad overrides via `PCSX.SIO0.slots[1].pads[1].setOverride()`.

### Why Two Channels?

The REST API has no Lua execution endpoint — `PCSX.WebServer` handler API is `nil` in most builds. The pad override API only exists in Lua. So pad control goes through file IPC, everything else through REST.

## Prerequisites

1. **PCSX-Redux** running with these settings (`Configuration > Emulation`):
   - ✅ Enable Web Server (port **8079**)
   - ✅ Enable Debugger *(optional, for breakpoints)*
   - ⚠️ Use **Interpreter** mode if you need Lua breakpoints (Dynarec doesn't support them)

2. **Load pad controller** in the PCSX-Redux Lua console:
   ```lua
   dofile("path/to/pad_control.lua")
   ```

## CLI Tool: `pcsx_cmd.py`

```bash
# Memory
python pcsx_cmd.py read 0x800BBDEC 32     # Hex dump
python pcsx_cmd.py u32 0x800BBC88         # Read uint32
python pcsx_cmd.py u16 0x800BBF0C         # Read uint16
python pcsx_cmd.py write 0x800BBDEC F7FF  # Write bytes

# Pad control (requires pad_control.lua loaded in emulator)
python pcsx_cmd.py press start 15         # Press Start for 15 frames
python pcsx_cmd.py press circle 15        # Press Circle for 15 frames
python pcsx_cmd.py press down 10          # Press Down for 10 frames
python pcsx_cmd.py release                # Release all

# Screenshots
python pcsx_cmd.py ss                     # Capture framebuffer as PNG
python pcsx_cmd.py screenshot output.png  # Capture to specific file

# Memory analysis
python pcsx_cmd.py scan 0x800B0000 65536 FFFF  # Find pattern
python pcsx_cmd.py watch 0x800BBC88 4 0.5      # Poll address
python pcsx_cmd.py diff 0x800BBDEC 288         # Snapshot + diff

# Emulator control
python pcsx_cmd.py pause
python pcsx_cmd.py resume
python pcsx_cmd.py status
python pcsx_cmd.py vram dump.bin
```

## MCP Bridge (for AI agents)

`pcsx_mcp_bridge.py` implements the [Model Context Protocol](https://modelcontextprotocol.io/) over stdio, translating JSON-RPC requests to REST API calls. Configure in your MCP client:

```json
{
  "mcpServers": {
    "pcsx-redux": {
      "command": "python",
      "args": ["path/to/pcsx_mcp_bridge.py"]
    }
  }
}
```

This gives AI coding agents (Claude, Cursor, etc.) direct access to live PS1 emulator state.

## Files

| File | Purpose |
|------|---------|
| `pcsx_cmd.py` | CLI tool — all human-facing commands |
| `pad_control.lua` | Lua VSync pad controller (loaded inside emulator) |
| `pcsx_mcp_bridge.py` | MCP JSON-RPC bridge (for AI agent integration) |

## Configuration

Edit `pcsx_cmd.py` to change:
- `BASE` — REST API base URL (default: `http://localhost:8079`)
- `SS_DIR` — Screenshot output directory
- `vram_to_png()` x/y/w/h — Framebuffer region (default: 320×240 at origin)

## Implementation Details

### Lua GC Bug (Solved)
All Lua event listeners MUST be stored in `_G` (global table). Local variables in `dofile()` scope get garbage collected when dofile returns, killing the event listener.

### Pad Override API
```lua
PCSX.SIO0.slots[1].pads[1].setOverride(PCSX.CONSTS.PAD.BUTTON.CIRCLE)  -- press
PCSX.SIO0.slots[1].pads[1].clearOverride(PCSX.CONSTS.PAD.BUTTON.CIRCLE) -- release
```
This overrides at the **hardware SIO level** — the game's own pad handler picks up the button state naturally.

### Screenshot Capture
Screenshots capture raw 16bpp VRAM (RGB555) via the REST API and convert to PNG using pure Python (zlib). No PIL/Pillow dependency.

## License

MIT
