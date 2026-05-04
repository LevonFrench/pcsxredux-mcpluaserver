-- pad_control.lua
-- Minimal pad controller with file-based IPC for PCSX-Redux.
-- Load in the Lua console: dofile("path/to/pad_control.lua")
--
-- All variables GLOBAL to survive GC after dofile() returns.
-- See README.md for why this is necessary.

local PAD = PCSX.CONSTS.PAD.BUTTON

-- Pad reference (Slot 1, Pad 1)
_G._pad = PCSX.SIO0.slots[1].pads[1]

-- Button name -> constant mapping
_G._pad_map = {
    select=PAD.SELECT, start=PAD.START, up=PAD.UP, down=PAD.DOWN,
    left=PAD.LEFT, right=PAD.RIGHT, cross=PAD.CROSS, circle=PAD.CIRCLE,
    triangle=PAD.TRIANGLE, square=PAD.SQUARE, l1=PAD.L1, l2=PAD.L2, r1=PAD.R1, r2=PAD.R2,
}

-- State
_G._pad_held = nil
_G._pad_frames = 0

-- Path to command file (same directory as this script)
-- pcsx_cmd.py writes commands here, we read and delete them
local script_dir = debug.getinfo(1, "S").source:match("@?(.*[/\\])")
if not script_dir then script_dir = "" end
_G._pad_cmd_path = script_dir .. "pad_cmd.txt"

-- Remove old listener if reloading
if _G._pad_listener then
    _G._pad_listener:remove()
    print("[PAD] Removed old listener")
end

_G._pad_listener = PCSX.Events.createEventListener("GPU::Vsync", function()
    -- Handle release countdown
    if _G._pad_held then
        _G._pad_frames = _G._pad_frames - 1
        if _G._pad_frames <= 0 then
            _G._pad.clearOverride(_G._pad_held)
            print("[PAD] Released")
            _G._pad_held = nil
        end
    end
    
    -- Check for command file
    local ok, err = pcall(function()
        local f = io.open(_G._pad_cmd_path, "r")
        if f then
            local line = f:read("*l")
            f:close()
            os.remove(_G._pad_cmd_path)
            
            if line and #line > 0 then
                local btn = line:match("^(%w+)")
                local dur = line:match("(%d+)$")
                local frames = tonumber(dur) or 15
                
                if btn == "release" then
                    if _G._pad_held then
                        _G._pad.clearOverride(_G._pad_held)
                        _G._pad_held = nil
                    end
                    print("[PAD] Force released")
                elseif _G._pad_map[btn] then
                    _G._pad.setOverride(_G._pad_map[btn])
                    _G._pad_held = _G._pad_map[btn]
                    _G._pad_frames = frames
                    print("[PAD] " .. btn .. " for " .. frames .. "f")
                else
                    print("[PAD] Unknown: " .. btn)
                end
            end
        end
    end)
    if not ok then
        print("[PAD] ERROR: " .. tostring(err))
    end
end)

print("[PAD] Controller ready. Command file: " .. _G._pad_cmd_path)
print("[PAD] Use: pcsx_cmd.py press <button> [frames]")
