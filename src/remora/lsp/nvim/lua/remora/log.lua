-- remora/log.lua — Timestamped file logger for the Neovim client side.
-- Each Neovim session gets a new log file: .remora/logs/client-YYYY-MM-DD_HHMMSS.log

local M = {}

M._file = nil
M._path = nil

--- Build a coherent wall-clock timestamp (HH:MM:SS + ms).
--- Using one source avoids out-of-order timestamps caused by mixing clocks.
--- @return string
--- @return integer
local function timestamp_parts()
    local uv = vim.uv or vim.loop
    if uv and uv.gettimeofday then
        local ok, a, b = pcall(uv.gettimeofday)
        if ok then
            local sec = nil
            local usec = 0
            if type(a) == "table" then
                sec = tonumber(a.sec or a.tv_sec or a[1])
                usec = tonumber(a.usec or a.tv_usec or a[2]) or 0
            else
                sec = tonumber(a)
                usec = tonumber(b) or 0
            end
            if sec then
                local ms = math.floor(usec / 1000)
                if ms < 0 then ms = 0 end
                if ms > 999 then ms = 999 end
                return os.date("%H:%M:%S", sec), ms
            end
        end
    end
    return os.date("%H:%M:%S"), 0
end

--- Initialize the log file. Safe to call multiple times (only opens once).
function M.init()
    if M._file then return end

    -- Find the workspace root (same as what the LSP client uses)
    local root = vim.fn.getcwd()
    local log_dir = root .. "/.remora/logs"
    vim.fn.mkdir(log_dir, "p")

    local stamp = os.date("%Y-%m-%d_%H%M%S")
    M._path = log_dir .. "/client-" .. stamp .. ".log"
    M._file = io.open(M._path, "w")
    if M._file then
        M._file:setvbuf("line")  -- flush every line
        M.info("=== Remora Neovim client log started: %s ===", M._path)
    end
end

--- Write a log line with timestamp and level.
function M._write(level, fmt, ...)
    if not M._file then M.init() end
    if not M._file then return end

    local msg = string.format(fmt, ...)
    local ts, ms = timestamp_parts()
    local line = string.format("[%s.%03d] %-5s %s\n", ts, ms, level, msg)
    M._file:write(line)
end

function M.debug(fmt, ...) M._write("DEBUG", fmt, ...) end
function M.info(fmt, ...)  M._write("INFO",  fmt, ...) end
function M.warn(fmt, ...)  M._write("WARN",  fmt, ...) end
function M.error(fmt, ...) M._write("ERROR", fmt, ...) end

--- Log a table as formatted JSON-ish string.
function M.dump(level, label, tbl)
    if not M._file then M.init() end
    if not M._file then return end
    M._write(level, "%s: %s", label, vim.inspect(tbl))
end

--- Close the log file (call on VimLeave or similar).
function M.close()
    if M._file then
        M.info("=== Remora Neovim client log closed ===")
        M._file:close()
        M._file = nil
    end
end

return M
