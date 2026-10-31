-- game-export.lua - File > Export to Game, for use with or without Claude.
-- Part of aseprite-claude-connector. Ships in the Claude Bridge extension.
--
-- Finds the engine from the folder, picks the project's sprites folder, and writes
-- what that engine needs. This is tools/game_export.py as a button, because the
-- button has to work when no server is running. tests/smoke_headless.py holds the
-- two byte-equal, so change them together.

local FOLDERS = {
  godot = { "sprites", "assets/sprites", "art/sprites", "assets", "art" },
  unity = { "Assets/Sprites", "Assets/Art" },
  folder = { "sprites", "assets/sprites", "assets" },
}

local UNITY_META = [[fileFormatVersion: 2
guid: __GUID__
TextureImporter:
  internalIDToNameTable:
__IDNAME__  externalObjects: {}
  serializedVersion: 12
  mipmaps:
    mipMapMode: 0
    enableMipMap: 0
    sRGBTexture: 1
    linearTexture: 0
    fadeOut: 0
    borderMipMap: 0
    mipMapsPreserveCoverage: 0
    alphaTestReferenceValue: 0.5
    mipMapFadeDistanceStart: 1
    mipMapFadeDistanceEnd: 3
  bumpmap:
    convertToNormalMap: 0
    externalNormalMap: 0
    heightScale: 0.25
    normalMapFilter: 0
  isReadable: 0
  streamingMipmaps: 0
  streamingMipmapsPriority: 0
  grayScaleToAlpha: 0
  generateCubemap: 6
  cubemapConvolution: 0
  seamlessCubemap: 0
  textureFormat: 1
  maxTextureSize: 2048
  textureSettings:
    serializedVersion: 2
    filterMode: 0
    aniso: 1
    mipBias: 0
    wrapU: 1
    wrapV: 1
    wrapW: 0
  nPOTScale: 0
  lightmap: 0
  compressionQuality: 50
  spriteMode: 2
  spriteExtrude: 1
  spriteMeshType: 1
  alignment: 0
  spritePivot: {x: 0.5, y: 0.5}
  spritePixelsToUnits: 100
  spriteBorder: {x: 0, y: 0, z: 0, w: 0}
  spriteGenerateFallbackPhysicsShape: 1
  alphaUsage: 1
  alphaIsTransparency: 1
  spriteTessellationDetail: -1
  textureType: 8
  textureShape: 1
  singleChannelComponent: 0
  maxTextureSizeSet: 0
  compressionQualitySet: 0
  textureFormatSet: 0
  ignorePngGamma: 0
  applyGammaDecoding: 0
  platformSettings:
  - serializedVersion: 3
    buildTarget: DefaultTexturePlatform
    maxTextureSize: 2048
    resizeAlgorithm: 0
    textureFormat: -1
    textureCompression: 1
    compressionQuality: 50
    crunchedCompression: 0
    allowsAlphaSplitting: 0
    overridden: 0
    androidETC2FallbackOverride: 0
    forceMaximumCompressionQuality_BC6H_BC7: 0
  spriteSheet:
    serializedVersion: 2
    sprites:
__SPRITES__    outline: []
    physicsShape: []
    bones: []
    spriteID:
    internalID: 0
    vertices: []
    indices:
    edges: []
    weights: []
    secondaryTextures: []
  spritePackingTag:
  pixelsPerUnit: 100
  mipBias: 0
  userData:
  assetBundleName:
  assetBundleVariant:
]]

local function engineAt(folder)
  if app.fs.isFile(app.fs.joinPath(folder, "project.godot")) then return "godot" end
  if app.fs.isDirectory(app.fs.joinPath(folder, "Assets"))
    and app.fs.isDirectory(app.fs.joinPath(folder, "ProjectSettings")) then
    return "unity"
  end
  return nil
end

local function parentOf(folder)
  local parent = folder:gsub("[\\/]+$", ""):match("^(.*)[\\/][^\\/]+$")
  if not parent or parent == "" or parent:match("^%a:$") then return nil end
  return parent
end

-- Returns the engine, its project root (nil for a plain folder), and the output folder.
local function locate(start)
  start = start:gsub("[\\/]+$", "")
  if not app.fs.isDirectory(start) then error("Game folder not found: " .. start) end
  local root, engine = start, engineAt(start)
  while not engine do
    root = parentOf(root)
    if not root then break end
    engine = engineAt(root)
  end
  if engine and root ~= start then return engine, root, start end
  local leaf = (start:match("[^\\/]+$") or ""):lower()
  if not engine and (leaf == "sprites" or leaf == "assets") then return "folder", nil, start end
  engine = engine or "folder"
  local first
  for _, sub in ipairs(FOLDERS[engine]) do
    local path = app.fs.normalizePath(app.fs.joinPath(start, sub))
    first = first or path
    if app.fs.isDirectory(path) then return engine, root, path end
  end
  return engine, root, first
end

local function writeText(path, text)
  local f, err = io.open(path, "wb")
  if not f then error(err) end
  f:write(text)
  f:close()
end

local function quoted(s)
  return '"' .. s:gsub("\\", "\\\\"):gsub('"', '\\"') .. '"'
end

local function number(x)
  local text = string.format("%.3f", x):gsub("0+$", "")
  if text:sub(-1) == "." then text = text .. "0" end
  return text
end

local function frameOrder(first, last, direction)
  local out = {}
  local function add(from, to, step)
    for n = from, to, step do out[#out + 1] = n end
  end
  if direction == AniDir.REVERSE then
    add(last, first, -1)
  elseif direction == AniDir.PING_PONG then
    add(first, last, 1)
    add(last - 1, first + 1, -1)
  elseif direction == AniDir.PING_PONG_REVERSE then
    add(last, first, -1)
    add(first + 1, last - 1, 1)
  else
    add(first, last, 1)
  end
  return out
end

local function animations(s)
  if #s.tags == 0 then
    return { { name = "default", frames = frameOrder(1, #s.frames), loop = true } }
  end
  local out, seen = {}, {}
  for _, tag in ipairs(s.tags) do
    local name = tag.name ~= "" and tag.name or "tag"
    seen[name] = (seen[name] or 0) + 1
    if seen[name] > 1 then name = name .. "_" .. seen[name] end
    local pass = frameOrder(tag.fromFrame.frameNumber, tag.toFrame.frameNumber, tag.aniDir)
    local frames = {}
    for _ = 1, math.max(tag.repeats, 1) do
      for _, n in ipairs(pass) do frames[#frames + 1] = n end
    end
    out[#out + 1] = { name = name, frames = frames, loop = tag.repeats == 0 }
  end
  return out
end

local function godotResource(s, resPath)
  local durations, used, numbers = {}, {}, {}
  for i, f in ipairs(s.frames) do durations[i] = math.floor(f.duration * 1000 + 0.5) end
  local anims = animations(s)
  for _, anim in ipairs(anims) do
    for _, n in ipairs(anim.frames) do
      if not used[n] then
        used[n] = true
        numbers[#numbers + 1] = n
      end
    end
  end
  table.sort(numbers)
  local lines = {
    string.format('[gd_resource type="SpriteFrames" load_steps=%d format=3]', #numbers + 2),
    "",
    '[ext_resource type="Texture2D" path=' .. quoted(resPath) .. ' id="1_sheet"]',
    "",
  }
  for _, n in ipairs(numbers) do
    lines[#lines + 1] = string.format('[sub_resource type="AtlasTexture" id="frame_%d"]', n)
    lines[#lines + 1] = 'atlas = ExtResource("1_sheet")'
    lines[#lines + 1] = string.format("region = Rect2(%d, 0, %d, %d)", (n - 1) * s.width, s.width, s.height)
    lines[#lines + 1] = ""
  end
  local entries = {}
  for _, anim in ipairs(anims) do
    local base = math.huge
    for _, n in ipairs(anim.frames) do base = math.min(base, durations[n]) end
    local frames = {}
    for i, n in ipairs(anim.frames) do
      frames[i] = string.format('{"duration": %s, "texture": SubResource("frame_%d")}',
        number(durations[n] / base), n)
    end
    entries[#entries + 1] = string.format('{"frames": [%s], "loop": %s, "name": &%s, "speed": %s}',
      table.concat(frames, ", "), anim.loop and "true" or "false", quoted(anim.name),
      number(1000 / base))
  end
  lines[#lines + 1] = "[resource]"
  lines[#lines + 1] = "animations = [" .. table.concat(entries, ", ") .. "]"
  lines[#lines + 1] = ""
  return table.concat(lines, "\n")
end

local function yamlScalar(s)
  if s:match("^[%w_][%w_ %.%-]*$") and s:sub(-1) ~= " " then return s end
  return quoted(s)
end

local function unityGuid(metaPath)
  local f = io.open(metaPath, "rb")
  if f then
    local guid = f:read("a"):match("guid: (%x+)")
    f:close()
    if guid and #guid == 32 then return guid end
  end
  math.randomseed(os.time() + os.clock() * 1000000)
  local out = {}
  for i = 1, 32 do out[i] = string.format("%x", math.random(0, 15)) end
  return table.concat(out)
end

local function unityMeta(s, stem, guid)
  local sprites, idName = {}, {}
  for i = 0, #s.frames - 1 do
    local name = stem .. "_" .. i
    local internal = 21300000 + i * 2
    sprites[#sprites + 1] = table.concat({
      "    - serializedVersion: 2\n",
      "      name: ", yamlScalar(name), "\n",
      "      rect:\n",
      "        serializedVersion: 2\n",
      "        x: ", i * s.width, "\n",
      "        y: 0\n",
      "        width: ", s.width, "\n",
      "        height: ", s.height, "\n",
      "      alignment: 9\n",
      "      pivot: {x: 0.5, y: 0.5}\n",
      "      border: {x: 0, y: 0, z: 0, w: 0}\n",
      "      outline: []\n",
      "      physicsShape: []\n",
      "      tessellationDetail: 0\n",
      "      bones: []\n",
      "      spriteID: ", guid:sub(1, 24), string.format("%08x", i), "\n",
      "      internalID: ", internal, "\n",
      "      vertices: []\n",
      "      indices: \n",
      "      edges: []\n",
      "      weights: []\n",
    })
    idName[#idName + 1] = string.format("  - first:\n      213: %d\n    second: %s\n",
      internal, yamlScalar(name))
  end
  local fields = {
    __GUID__ = guid,
    __IDNAME__ = table.concat(idName),
    __SPRITES__ = table.concat(sprites),
  }
  return (UNITY_META:gsub("__%u+__", fields))
end

-- Writes the export and returns what it did. Doesn't change the sprite.
local function exportTo(s, gameFolder, stem)
  local engine, root, folder = locate(gameFolder)
  app.fs.makeAllDirectories(folder)
  local png = app.fs.joinPath(folder, stem .. ".png")
  app.command.ExportSpriteSheet{
    ui = false,
    type = SpriteSheetType.HORIZONTAL,
    textureFilename = png,
    trim = false,
    borderPadding = 0,
    shapePadding = 0,
    innerPadding = 0,
  }
  local done = { engine = engine, png = png }
  if engine == "unity" then
    done.meta = png .. ".meta"
    writeText(done.meta, unityMeta(s, stem, unityGuid(done.meta)))
  elseif engine == "godot" and #s.frames > 1 then
    local relative = png:sub(#root + 2):gsub("\\", "/")
    done.tres = app.fs.joinPath(folder, stem .. ".tres")
    writeText(done.tres, godotResource(s, "res://" .. relative))
  end
  return done
end

ClaudeGameExport = { exportTo = exportTo }

local function stemOf(s)
  return app.fs.fileTitle(s.filename)
end

local function showDialog(prefs)
  local s = app.activeSprite
  if not s then
    app.alert("Open a sprite first.")
    return
  end
  local dlg
  dlg = Dialog{ title = "Export to Game" }
  dlg:entry{ id = "folder", label = "Game folder:", text = prefs.gameFolder or "" }
  dlg:file{
    id = "pick", label = "", title = "Pick any file in your game folder", open = true,
    onchange = function()
      local picked = dlg.data.pick
      if picked ~= "" then dlg:modify{ id = "folder", text = app.fs.filePath(picked) } end
    end,
  }
  dlg:entry{ id = "name", label = "Name:", text = stemOf(s) }
  dlg:button{ id = "ok", text = "Export", focus = true }
  dlg:button{ id = "cancel", text = "Cancel" }
  dlg:show()
  local data = dlg.data
  if not data.ok then return end
  if data.folder == "" or data.name == "" then
    app.alert("Choose a game folder and a name.")
    return
  end
  local ok, res = pcall(exportTo, s, data.folder, data.name)
  if not ok then
    app.alert{ title = "Export to Game", text = tostring(res) }
    return
  end
  prefs.gameFolder = data.folder
  local where = res.engine == "folder" and "your folder" or res.engine
  app.alert{ title = "Export to Game", text = { "Ready to select in " .. where .. ":", res.png } }
end

function init(plugin)
  plugin:newCommand{
    id = "ClaudeExportToGame",
    title = "Export to Game...",
    group = "file_export_1",
    onclick = function() showDialog(plugin.preferences) end,
  }
end
