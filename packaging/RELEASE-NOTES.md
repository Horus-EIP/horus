First beta build of Horus. Everything runs locally on your machine — no data
leaves it.

## Before you start

| | |
|---|---|
| **Docker Desktop** | installed **and running** |
| **Python 3.11+** | only used to run the installer |
| **NVIDIA GPU** | strongly recommended — see Known limitations |
| **Free disk** | 150 GB while installing (125 GB with an NVIDIA GPU), settling to 130 GB / 110 GB |
| **Time** | 1.5 to 2 hours for the first install when testers built the containers; downloading the prebuilt ones has not been timed yet |
| **Access token** | the one we sent you, saved as `registry-token.txt` next to `START-HERE`, on one line: `USERNAME:TOKEN` |

## Install

1. Download `Horus-Beta-<version>.zip` below and extract **all** of it
2. Save your access token as `registry-token.txt` in the extracted folder
3. From inside the extracted folder:
   - **Windows** — double-click `START-HERE-Windows.bat`
   - **macOS** — right-click `START-HERE-macOS.command` → Open
   - **Linux** — `./START-HERE-Linux.sh`
4. It asks two or three questions, then downloads everything. Horus's own
   containers come prebuilt and signed, so nothing is built on your machine.
   It is not frozen — leave it running.
5. When it finishes, open Horus from the `app/` folder:
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
- The first install downloads about 26.5 GB of container images and model
  weights with an NVIDIA GPU (measured). On the CPU it is about 16.6 GB,
  derived from the 25 GB we measured before the CPU model changed: the two
  models the containers downloaded (11.2 GB) are gone, and a 2.5 GB model
  file and a 0.3 GB model server came in. The install needs 150 GB / 125 GB
  of free disk while it builds, settling to 130 GB / 110 GB afterwards
  (measured before that change).
- All of those figures were measured when testers built the containers. The
  containers now come prebuilt and signed; the download size, the time and
  the disk they need have not been measured yet, so the installer still asks
  for the same free space.
- The prebuilt containers are built for x86-64 processors. On an Apple
  Silicon Mac Docker runs them through emulation; if that fails, run your
  `START-HERE` file with `--build-from-source` to build them on the Mac.
- On the CPU the installer downloads the language model itself, shows its
  size, speed and time left, resumes an interrupted download and checks its
  SHA-256. It is kept in `horus/models`, also after `--uninstall`.
- Your documents are mounted **read-only**. Horus cannot modify anything you own.

## If something goes wrong

Send us **`install-log.txt`** and **`horus-profile.json`** from the folder you
extracted. They contain no passwords and show exactly what happened.

To stop, keeping your data: run your `START-HERE` file with `--stop`
To remove everything: run it with `--uninstall` — this deletes ingested documents.
