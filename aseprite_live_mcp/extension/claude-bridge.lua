-- claude-bridge.lua - live control channel into THIS running Aseprite.
-- Part of aseprite-live-mcp. Ships as the Claude Bridge extension.
--
-- Connects to the local relay on launch and keeps retrying in the background, so
-- nothing has to be started by hand. File > Scripts > Claude Bridge opens a status
-- panel: connection state, active-document info, a live activity log, and a Pause
-- toggle (reject commands without disconnecting), which is remembered between runs.
--
-- The relay sends Lua snippets over a local WebSocket; they execute HERE against
-- the live app - every open file (app.sprites), the active frame/layer/cel,
-- unsaved state included. The caller wraps its edits in app.transaction so each
-- edit is a single undo step (Ctrl+Z reverts it like any of your own actions).

local PORT = 9877
local prefs = nil
local ws = nil
local heartbeat = nil
local dlg = nil
local connectAsked = false
local statusText = "waiting for Claude"
local execCount = 0
local errCount = 0
local ticks = 0
local logLines = { "", "", "" }

local function setLabel(id, text)
  if dlg then pcall(function() dlg:modify{ id = id, text = text } end) end
end

local function setStatus(text)
  statusText = text
  setLabel("status", text)
end

local function updateInfo()
  if not dlg then return end
  local s = app.activeSprite
  local doc = "none"
  if s then
    local name = tostring(s.filename):match("[^\\/]+$") or "untitled"
    doc = name .. " (" .. s.width .. "x" .. s.height .. ", " .. #s.frames .. "f)"
  end
  setLabel("aseinfo", "Aseprite " .. tostring(app.version) .. "   open docs: " .. #app.sprites)
  setLabel("docinfo", "Active: " .. doc)
end

local function pushLog(text)
  table.insert(logLines, 1, text)
  logLines[4] = nil
  for i = 1, 3 do setLabel("log" .. i, logLines[i] or "") end
end

local function handle(msg)
  local nl = msg:find("\n", 1, true)
  if not nl then return end
  local id   = msg:sub(1, nl - 1)
  local code = msg:sub(nl + 1)

  if prefs.paused then
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

local function showPanel()
  if dlg then return end
  dlg = Dialog{ title = "Claude Bridge", onclose = function() dlg = nil end }
  dlg:label{ id = "status", label = "Status:", text = statusText }
  dlg:newrow()
  dlg:label{ id = "aseinfo", label = "", text = "Aseprite -                              " }
  dlg:newrow()
  dlg:label{ id = "docinfo", label = "", text = "Active: -" }
  dlg:separator{ text = "Recent activity" }
  dlg:label{ id = "log1", label = "", text = logLines[1] }
  dlg:newrow()
  dlg:label{ id = "log2", label = "", text = logLines[2] }
  dlg:newrow()
  dlg:label{ id = "log3", label = "", text = logLines[3] }
  dlg:separator()
  dlg:check{
    id = "pause", text = "Pause (reject commands, stay connected)", selected = prefs.paused,
    onclick = function()
      prefs.paused = dlg.data.pause
      setStatus(prefs.paused and "PAUSED (rejecting commands)" or "connected")
    end,
  }
  dlg:show{ wait = false }
  updateInfo()
end

function init(plugin)
  prefs = plugin.preferences
  prefs.paused = prefs.paused or false

  plugin:newCommand{
    id = "ClaudeBridgePanel",
    title = "Claude Bridge",
    group = "file_scripts",
    onclick = showPanel,
  }

  -- NOTE: the callback is `onreceive(messageType, data)` per the official API
  -- (docs: aseprite/api websocket.md) - NOT per-type callbacks. An `onreceivetext`
  -- param is SILENTLY IGNORED (sends work, receives vanish) - do not "fix" this.
  ws = WebSocket{
    url = "ws://127.0.0.1:" .. PORT,
    deflate = false,
    minreconnectwait = 1,
    maxreconnectwait = 5,
    onreceive = function(mt, data)
      if mt == WebSocketMessageType.TEXT then
        local ok, err = pcall(handle, data)
        if not ok and ws then
          pcall(function() ws:sendText("__handler__\nERR\n" .. tostring(err)) end)
        end
      elseif mt == WebSocketMessageType.OPEN then
        setStatus("connected to Claude")
        updateInfo()
      elseif mt == WebSocketMessageType.CLOSE then
        setStatus("waiting for Claude")
      end
    end,
  }

  -- Heartbeat: Aseprite only dispatches websocket callbacks while its event loop is
  -- awake; an idle/unfocused editor starves them. A ticking Timer keeps the loop
  -- pumping so the bridge responds even when Aseprite is in the background.
  -- The first tick connects, not init: the first connection can raise Aseprite's
  -- access prompt, which needs the UI to be up.
  heartbeat = Timer{
    interval = 0.15,
    ontick = function()
      if not connectAsked then
        connectAsked = true
        ws:connect()
      end
      ticks = ticks + 1
      if ticks % 33 == 1 then
        pcall(function() ws:sendText("__beacon__\nOK\nlua alive, ticks=" .. ticks) end)
        updateInfo()
      end
    end,
  }
  heartbeat:start()
end

function exit(plugin)
  if heartbeat then heartbeat:stop() end
  if ws then ws:close() end
end
