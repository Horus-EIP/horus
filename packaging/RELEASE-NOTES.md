First beta build of Horus. Everything runs locally on your machine — no data
leaves it.

## Before you start

| | |
|---|---|
| **Docker Desktop** | installed **and running** |
| **Python 3.11+** | only used to run the installer |
| **NVIDIA GPU** | strongly recommended — see Known limitations |
| **Free disk** | 150 GB while installing (125 GB with an NVIDIA GPU), settling to 130 GB / 110 GB |
| **Time** | 1.5 to 2 hours for the first install |

## Install

1. Download `Horus-Beta-<version>.zip` below and extract **all** of it
2. From inside the extracted folder:
   - **Windows** — double-click `START-HERE-Windows.bat`
   - **macOS** — right-click `START-HERE-macOS.command` → Open
   - **Linux** — `./START-HERE-Linux.sh`
3. It asks two or three questions, then downloads and builds everything.
   It is not frozen — leave it running.
4. When it finishes, open Horus from the `app/` folder:
   - Windows: `app/Horus.exe`
   - macOS: `app/Horus.app`
   - Linux: install `app/Horus_<version>_amd64.deb`, then launch Horus

   Or just open `http://localhost:3000` in any browser.

## Your computer will warn you

These apps are not code-signed yet.

- **Windows** — "Windows protected your PC" → **More info** → **Run anyway**
- **macOS** — "cannot be opened because the developer cannot be verified" →
  **right-click the app → Open → Open**. Double-clicking will not work the
  first time.

Would rather not bypass an OS warning? Fair. Use the browser at
`http://localhost:3000` instead — it is a fully supported path.

## Known limitations

- **Without an NVIDIA GPU, Horus is not usable yet.** On CPU a single question
  took **14 minutes** and returned a wrong answer. With a GPU the same question
  answers in about 4 seconds. If you have no NVIDIA GPU, the stack will install
  and every part of it works except the model itself.
- The first install downloads about 25 GB (CPU) or 26.5 GB (GPU) of
  container images and model weights, and needs 150 GB / 125 GB of free
  disk while it builds, settling to 130 GB / 110 GB afterwards.
- Your documents are mounted **read-only**. Horus cannot modify anything you own.

## If something goes wrong

Send us **`install-log.txt`** and **`horus-profile.json`** from the folder you
extracted. They contain no passwords and show exactly what happened.

To stop, keeping your data: run your `START-HERE` file with `--stop`
To remove everything: run it with `--uninstall` — this deletes ingested documents.
