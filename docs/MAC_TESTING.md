# Testing on a Mac without buying Aseprite

CI checks setup and every tool on a Mac, but one thing needs a person: the first time
Aseprite's Claude Bridge extension connects, Aseprite asks for permission, and only a
person can answer that. These steps cover it for free, in about 30 minutes, most of it
waiting for a build. You don't need Claude, or to have used Aseprite before.

Aseprite's free trial can't do this, because it blocks extensions. But Aseprite's
licence lets anyone compile it from source for their own use, which is what CI does on
every run. You'd be building your own copy, for yourself only: don't share the app you
build.

## 1. Build Aseprite

In Terminal:

```bash
xcode-select --install                     # Apple's build tools, if you don't have them
brew install cmake ninja                   # needs Homebrew: https://brew.sh
git clone --recursive --depth 1 --shallow-submodules --branch v1.3.17.2 \
  https://github.com/aseprite/aseprite.git ~/aseprite
cd ~/aseprite && ./build.sh --auto --norun
```

The build downloads what it needs and takes 10-20 minutes. Aseprite ends up at
`~/aseprite/build/bin/aseprite`.

## 2. Install the connector

You need Python 3.10 or newer (`python3 --version`; get it from python.org if not).

```bash
python3 -m pip install aseprite-claude-connector
aseprite-claude-connector setup --no-register
```

`--no-register` skips connecting it to Claude Code, which you don't need for this.

## 3. Connect

Start the connector's relay in one Terminal window and leave it running:

```bash
python3 -m aseprite_claude_connector.relay
```

Then open Aseprite from a second window:

```bash
~/aseprite/build/bin/aseprite
```

Aseprite asks once whether to allow the Claude Bridge connection. Tick the box to
remember it, then allow it.

## 4. Check it worked

In the second window:

```bash
curl http://127.0.0.1:9878/status
```

You should see `"connected": true` and Aseprite's version. Then send it something to
draw:

```bash
curl -s -X POST http://127.0.0.1:9878/exec --data \
  'local s = Sprite(32, 32) s.cels[1].image:clear(Color(220, 60, 60)) app.refresh() return "drew it"'
```

A new red 32×32 sprite should appear in Aseprite.

## 5. Report back

Send the maintainer:

- what the two `curl` commands printed
- whether the permission prompt appeared, and whether the red sprite did
- your macOS version, and whether it's an Apple Silicon or Intel Mac

Then quit Aseprite with Cmd+Q and stop the relay with Ctrl+C. To remove everything:
`python3 -m pip uninstall aseprite-claude-connector`, delete `~/aseprite`, and delete
the `aseprite-claude-connector` folder in Aseprite's `extensions` folder, which is in
`~/Library/Application Support/Aseprite/`.
