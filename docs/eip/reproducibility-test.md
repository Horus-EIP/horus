# Reproducibility test by an outsider

**Objective:** Tek5 Objective 1, action 1.5. Someone outside Epitech installs Horus using only the README and the installer, and we record who, when, how long it took, what blocked them, and what we fixed.

**Backlog:** B-39. Blockers found here become GitHub issues.

---

## 1. Rules

- **Who:** a person who is not an Epitech student, mentor or staff member, and who has never installed Horus.
- **Before the test:** they sign the Horus Contributor Agreement and tick "Access only". Nobody gets the bundle, the code or a registry token before that.
- **What they get:** one of these, and nothing else (no call, no extra explanation):
  - the release ZIP (named after the version, for example `Horus-Beta-0.1.2.zip`), whose readme is `README-FIRST.txt`, plus a registry access token. The installer downloads Horus's prebuilt images from our private registry, so it needs the token, saved as `registry-token.txt` next to the START-HERE files;
  - or the repository, whose readme is `README.md`. Its installer, `installer/horus_install.py`, also downloads the prebuilt images and needs the same token, saved as `registry-token.txt` at the repository root, unless they run it with `--build-from-source`.
- **When we help:** only when they have been stuck for 15 minutes, or when they ask. Every time we help, it is written in the blockers table, with what we said.
- **Who watches:** one of us, on a call or next to them, with a timer. The tester talks through what they do.
- **Their machine:** any machine they have. We record what it is; the installer decides the profile. If the installer refuses the machine, that is a result too: write it down.

---

## 2. The test

| | |
|---|---|
| Tester (name or pseudonym) | |
| Background (developer? Docker before?) | |
| Date | |
| Observer | |
| Horus version (the `VERSION` file) and commit | |
| ZIP or repository | |
| Prebuilt images or `--build-from-source` | |

### Machine

| | |
|---|---|
| OS and version | |
| CPU | |
| RAM | |
| GPU and VRAM (or none) | |
| Free disk before the install | |
| Docker and Docker Compose versions | |
| Profile chosen by the installer (`profile:` line after "Checking your hardware") | |

### Steps and times

The tester does each step from the readme they were given. The observer writes the time each one starts and ends. The names in quotes are the headings the installer prints.

| # | Step | Start | End | Duration | Notes |
|---|---|---|---|---|---|
| 1 | Download and extract the ZIP, or clone the repository | | | | |
| 2 | Install the prerequisites the readme lists: Docker (Docker Desktop on Windows and macOS) with Docker Compose 2.33 or newer, and Python 3.11 or newer for the installer. Save the token as `registry-token.txt` | | | | |
| 3 | Start the installer (the START-HERE file for their system, or `python installer/horus_install.py`) and go through the checks, from "1/6  Python" to "Preflight passed." | | | | |
| 4 | Answer "What should Horus be allowed to read?", then wait through "Downloading container images" ("Building the images" with `--build-from-source`) and, on a CPU profile, "Downloading the language model" | | | | |
| 5 | First start: "Starting the stack", "Waiting for services to become healthy" (on a GPU profile the model downloads here) and "Verifying the installation", until the installer prints "Horus is running." | | | | |
| 6 | Open http://localhost:3000 (or the Horus app in the `app` folder of the ZIP) and sign in with the username the installer prints after "Sign in as" and the password it prints after "Password" (shown once) | | | | |
| 7 | Upload a document on the Knowledge Store page | | | | |
| 8 | Ask a question about it in Chat; the answer lists the document under "Sources" | | | | |
| 9 | Stop Horus and start it again: run the START-HERE file (or `installer/horus_install.py`) with `--stop`, then with `--start`, or use the Horus app | | | | |
| | **Total** | | | | |

The sign-in details come from `SUPER_USER_USERNAME` and `SUPER_USER_PASSWORD` in `src/infra/.env`, which the installer creates from `src/infra/.env.example`; it generates the password and prints it once, at the end, never in `install-log.txt`. On a CPU profile the installer warns at the end that answers take minutes, not seconds: time step 8 anyway.

### Blockers

| # | Step | What happened | How it was solved | Did we help? | Issue |
|---|---|---|---|---|---|
| | | | | | |

---

## 3. Result

- **Did they get a correct answer with its source without our help?**
- **Total time**, and the slowest step:
- **What we changed afterwards** (commit or issue for each blocker):
- **What the tester said** (two or three quotes, with their agreement):

---

## 4. After the test

1. Keep the tester's `install-log.txt` and `horus-profile.json` with this form. The installer writes both next to the START-HERE files, or at the repository root when it runs from a clone. They hold no passwords and no registry token.
2. Open one issue per blocker, labelled `bug` or `documentation`, and link it in the table.
3. Fix the readme or the installer where the tester got lost.
4. Add the tester to [CONTRIBUTORS.md](../../CONTRIBUTORS.md) if they agree to be credited.
5. Log the test as done in the backlog (B-39).
