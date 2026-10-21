# Horus desktop shell

A thin native window that runs the Horus stack and then displays the existing
web client in it, so a tester never has to be told to open `localhost:3000`.

```
desktop/
├── ui/                     the status screen: 3 static files, no bundler
├── src-tauri/              the Rust shell
│   ├── src/                ~700 lines, split by concern
│   ├── icons/              generated, committed (see "Icons")
│   ├── capabilities/       what the status window may call
│   └── tauri.conf.json
├── tools/make_icon_source.py   builds the 1024px icon master, stdlib only
├── icon-source.png         that master, committed so CI needs no image tooling
└── package.json            one devDependency: the Tauri CLI
```

## What it does, in order

1. Shows a window immediately, before probing anything, so a slow Docker check
   cannot look like a launch that did nothing.
2. Finds the unzipped bundle, the Horus source inside it, and a Python 3.11+
   interpreter. Each failure has its own screen with the one instruction that
   fixes it.
3. Runs `installer/horus_install.py --start --json-events` and renders the
   stream: current step, a progress bar while the CPU language model downloads,
   one row per service with its health, elapsed time, and the raw Docker
   output behind a disclosure triangle.
4. On the installer's `ready` event, opens a second window at
   `https://localhost:3000` and hides the status window.
5. Leaves Stop / Restart / Open install-log.txt / Open horus-profile.json on the
   native menu **and** on the status window, because the app window shows a
   remote page that has no way to call back into the shell.
6. On close, asks whether to leave the stack running, and remembers the answer.

## It reimplements nothing

Every lifecycle action shells out to `installer/horus_install.py`. The Rust in
here manages windows, spawns a process, parses one line format and opens files.

That is a deliberate constraint, not laziness. The installer already implements
start / restart / stop with a distinct exit code per failure and unit tests
behind it, in a language everyone here can run and two of the three target
platforms cannot compile Rust for locally. A second implementation would be a
second thing to keep correct and the first thing to drift. The shell does not
know what a healthy service is, how long a start should take, or that `docker`
exists.

The contract is two lines wide:

* **stdout** is the human transcript, forwarded verbatim to the output pane.
* **stderr** carries `@@HORUS {json}` lines, one per event, only when
  `--json-events` is passed. Anything on stderr without that prefix is treated
  as output, so a Python traceback shows up instead of being silently eaten.

`installer/common.py` owns the prefix and the `Events` class; every `log.step()`
/ `ok()` / `warn()` in the installer is mirrored automatically, and
`wait_for_health()` adds a `services` event on every poll. The model manager
adds `download` events (phase, bytes done and total, percent, speed, time left
and a ready-made line of text) twice a second while it downloads, then one each
for `verifying` and `verified` or `failed`.

A machine the installer refuses gets one `unsupported` event (what the machine
has, what Horus needs, what to do) and exit code 32, which the app shows on its
own screen. The refusal stays in `horus-profile.json`, so `bootstrap` reports
`refused` while nothing is installed and the app runs `--start`, which repeats
it. A later install run that gets past the hardware decision clears it.

## Two windows, and why the client is not bundled

The status screen is a local page; the Horus client is a remote one. They cannot
be the same document, and the client **must** keep being served from
`https://localhost:3000` by its own container:

* its session token lives in the `localStorage` of that origin, so re-hosting
  the client - bundling a static export, proxying it, serving it from the app -
  signs the tester out on every launch and reads as a login bug;
* `web-client` is `output: "standalone"` with four server route handlers, so it
  is not statically exportable in the first place.

The app window is therefore given **no IPC access at all**: `capabilities/`
scopes everything to the `status` window by name. The client does not know the
shell exists and cannot reach into it.

## Building

```bash
cd desktop && npm install && npm run build:windows
```

Needs Rust (`rustup`) plus the platform's own webview toolchain. Tauri cannot
cross-compile these three targets from one machine, so
`.github/workflows/desktop-release.yml` is the only thing that builds all of
them: push a tag, or run it from the Actions tab.

| Platform | Command | Artefact | Built so far |
|---|---|---|---|
| Windows | `npm run build:windows` | `target/release/Horus.exe`, no installer | yes - 5.8 MB, Rust 1.98, 2026-09-01 |
| macOS | `npm run build:macos` | `Horus.app`, universal (both slices) | CI only, never run |
| Linux | `npm run build:linux` | `.deb` | CI only, never run |

Every script passes `--locked`, so the committed `Cargo.lock` (431 packages) is
authoritative: a build fails rather than quietly resolving a different tree.

An **AppImage is deliberately not built**: it embeds WebKitGTK, 70-100 MB, which
exceeds the whole 50 MB archive budget on its own. The `.deb` links the system
`webkit2gtk` and is a few MB. Non-Debian Linux uses the documented browser path.

`npx tauri info` works without Rust and will say what is missing.

Before committing a change to `src-tauri/`, from that directory:

```bash
cargo fmt --check && cargo clippy --all-targets && cargo check
```

All three are clean as of 2026-09-01. They are deliberately **not** in the
release workflow: it is tag-triggered, and blocking a release on a style lint
that a floating `stable` toolchain introduced would cost more than it catches.

## Icons

`src/services/web-client/public/logo.png` cannot be used as an app icon as it
is, for two measured reasons: it is a **pure black glyph on a fully transparent
background** (31107 of its 40000 pixels have alpha 0), which disappears against
a dark taskbar or dock - the default on Windows 11 and on macOS in dark mode -
and it is 200x200 where macOS wants 1024.

`tools/make_icon_source.py` composites that same mark, unaltered, onto an opaque
white rounded plate: crops to the ink (the artwork sits off-centre in its own
canvas), enlarges it 5x with nearest-neighbour so nothing blurs, and centres it
on 1024x1024. Standard library only - no Pillow, no network.

```bash
python desktop/tools/make_icon_source.py
npx @tauri-apps/cli icon desktop/icon-source.png -o desktop/src-tauri/icons
```

The generated set is committed because a build must not depend on image tooling
being present. The Android, iOS and Windows-Store sizes `tauri icon` also emits
are deleted - none of those targets are built.

Worth knowing: the small sizes are as sharp as a 200px original allows, and no
sharper. A real 1024px master would improve them, and nothing else needs to
change to use one.

## Known limits

* **Unsigned.** Windows SmartScreen and macOS Gatekeeper both object. The exact
  click-path is in `packaging/README-FIRST.txt`, and the browser at
  `localhost:3000` stays a supported way to use Horus for anyone who would
  rather not bypass their operating system's warning.
* **Python is required to open the app**, not just to install it, because the
  shell drives the installer. If it is missing the app says so and links to the
  download, rather than failing silently.
* **On Linux the app is a `.deb`**, so it installs to `/usr/bin` and has no
  relationship to the unzipped folder. It searches the usual places, and if it
  cannot find the folder it asks for the path once and remembers it.
* **The menu is best-effort.** If a platform refuses to build it, the shell logs
  that and carries on - every menu item is also a button on the status window.
