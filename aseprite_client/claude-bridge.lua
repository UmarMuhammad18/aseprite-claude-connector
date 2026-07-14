-- claude-bridge.lua - live control channel into THIS running Aseprite.
-- Part of aseprite-live-mcp.
--
-- Run from File > Scripts (grant the script full trust when asked - it needs
-- localhost network access to reach the relay on 127.0.0.1). A status panel stays
-- open while the bridge runs: connection state, Aseprite + active-document info, a
-- live activity log (last commands + errors), a Pause toggle (reject commands
-- without disconnecting), and Stop. Closing the panel stops the bridge.
--
-- The relay sends Lua snippets over a local WebSocket; they execute HERE against
-- the live app - every open file (app.sprites), the active frame/layer/cel,
-- unsaved state included. The caller wraps its edits in app.transaction so each
-- edit is a single undo step (Ctrl+Z reverts it like any of your own actions).

if WebSocket == nil then
  app.alert("This Aseprite has no WebSocket support - the bridge needs Aseprite v1.3+.")
  return
end

local PORT = 9877
local execCount = 0
local errCount = 0
local paused = false
local ws = nil
local logLines = { "", "", "" }
local dlg = Dialog{ title = "Claude Bridge" }

local function setStatus(text)
  pcall(function() dlg:modify{ id = "status", text = text } end)
end

local function updateInfo()
  local ver = tostring(app.version)
  local n = #app.sprites
  local s = app.activeSprite
  local doc = "none"
  if s then
    local name = tostring(s.filename):match("[^\\/]+$") or "untitled"
    doc = name .. " (" .. s.width .. "x" .. s.height .. ", " .. #s.frames .. "f)"
  end
  pcall(function() dlg:modify{ id = "aseinfo", text = "Aseprite " .. ver .. "   open docs: " .. n } end)
  pcall(function() dlg:modify{ id = "docinfo", text = "Active: " .. doc } end)
end

local function pushLog(text)
  table.insert(logLines, 1, text)
  logLines[4] = nil
  pcall(function() dlg:modify{ id = "log1", text = logLines[1] or "" } end)
  pcall(function() dlg:modify{ id = "log2", text = logLines[2] or "" } end)
  pcall(function() dlg:modify{ id = "log3", text = logLines[3] or "" } end)
end

local function handle(msg)
  local nl = msg:find("\n", 1, true)
  if not nl then return end
  local id   = msg:sub(1, nl - 1)
  local code = msg:sub(nl + 1)

  if paused then
    ws:sendText(id .. "\nERR\nbridge paused by user")
    pushLog("- (paused, rejected)")
    return
  end

  local fn, compileErr = load(code, "claude")
  if not fn then
    ws:sendText(id .. "\nERR\ncompile: " .. tostring(compileErr))
    return
  end

  local ok, res = pcall(fn)
  execCount = execCount + 1
  if ok then
    ws:sendText(id .. "\nOK\n" .. (res == nil and "" or tostring(res)))
    pushLog("#" .. execCount .. " ok")
  else
    errCount = errCount + 1
    ws:sendText(id .. "\nERR\n" .. tostring(res))
    pushLog("#" .. execCount .. " ERR: " .. tostring(res):sub(1, 40))
  end

  setStatus("connected - " .. execCount .. " run, " .. errCount .. " err")
  updateInfo()
  app.refresh()
end

-- NOTE: the callback is `onreceive(messageType, data)` per the official API
-- (docs: aseprite/api websocket.md) - NOT per-type callbacks. An `onreceivetext`
-- param is SILENTLY IGNORED (sends work, receives vanish) - do not "fix" this.
ws = WebSocket{
  url = "ws://127.0.0.1:" .. PORT,
  deflate = false,
  onreceive = function(mt, data)
    if mt == WebSocketMessageType.TEXT then
      local ok, err = pcall(handle, data)
      if not ok and ws then
        pcall(function() ws:sendText("__handler__\nERR\n" .. tostring(err)) end)
      end
    elseif mt == WebSocketMessageType.OPEN then
      pcall(setStatus, "connected to Claude")
      pcall(updateInfo)
    elseif mt == WebSocketMessageType.CLOSE then
      pcall(setStatus, "disconnected - retrying...")
    end
  end,
}

-- Heartbeat: Aseprite only dispatches websocket callbacks while its event loop is
-- awake; an idle/unfocused editor starves them. A ticking Timer keeps the loop
-- pumping so the bridge responds even when Aseprite is in the background.
-- Every ~5s it also sends a beacon frame + refreshes the info panel.
local heartbeat = nil
local ticks = 0
if Timer ~= nil then
  heartbeat = Timer{
    interval = 0.15,
    ontick = function()
      ticks = ticks + 1
      if ticks % 33 == 1 and ws ~= nil then
        pcall(function() ws:sendText("__beacon__\nOK\nlua alive, ticks=" .. ticks) end)
        pcall(updateInfo)
      end
    end,
  }
end

dlg:label{ id = "status", label = "Status:", text = "connecting to 127.0.0.1:" .. PORT .. " ..." }
dlg:newrow()
dlg:label{ id = "aseinfo", label = "", text = "Aseprite -                              " }
dlg:newrow()
dlg:label{ id = "docinfo", label = "", text = "Active: -" }
dlg:separator{ text = "Recent activity" }
dlg:label{ id = "log1", label = "", text = "" }
dlg:newrow()
dlg:label{ id = "log2", label = "", text = "" }
dlg:newrow()
dlg:label{ id = "log3", label = "", text = "" }
dlg:separator()
dlg:check{
  id = "pause", text = "Pause (reject commands, stay connected)", selected = false,
  onclick = function()
    paused = dlg.data.pause
    setStatus(paused and "PAUSED (rejecting commands)" or ("connected - " .. execCount .. " run"))
  end,
}
dlg:button{
  text = "Stop bridge",
  onclick = function()
    if heartbeat then heartbeat:stop() end
    if ws then ws:close() end
    dlg:close()
  end,
}
dlg:show{ wait = false }

ws:connect()
if heartbeat then heartbeat:start() end
setStatus("bridge started - waiting for Claude" .. (heartbeat and "" or " (no Timer API - keep Aseprite focused)"))
updateInfo()
