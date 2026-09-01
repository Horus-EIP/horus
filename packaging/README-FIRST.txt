HORUS - BETA TEST BUILD
=======================
BEFORE YOU START you need Docker Desktop installed AND RUNNING
(https://www.docker.com/products/docker-desktop/), Python 3.11+
(https://www.python.org/downloads/), 40 GB free disk, and internet.

TO INSTALL
  Windows  double-click  START-HERE-Windows.bat
  macOS    RIGHT-CLICK   START-HERE-macOS.command  and choose Open
  Linux    run           ./START-HERE-Linux.sh
It asks two or three questions, then downloads and starts everything.
The first run takes 10-30 minutes: it builds containers, then downloads
an AI model. It is NOT frozen. Leave it running and it will finish.

SECURITY WARNINGS ARE EXPECTED
Our apps are not code-signed yet, so your computer will warn you:
  Windows: "Windows protected your PC"
           click  More info  then  Run anyway
  macOS:   "cannot be opened because the developer cannot be verified"
           RIGHT-CLICK the file, choose Open, then Open again.
           Double-clicking will NOT work the first time.
Prefer not to bypass a warning? Fair. Use the browser instead (below).

WHEN IT FINISHES
Open Horus from the app folder here (Linux: install the .deb in it) -
it starts and stops Horus for you. Or use http://localhost:3000.
Sign in with the username and password the installer prints at the end.

ABOUT YOUR FILES
The installer asks which folders Horus may read and mounts them
read-only. Unsure? Pick option 1: it uses our sample documents.

IF SOMETHING GOES WRONG
Send us install-log.txt and horus-profile.json from this folder.
They hold no passwords, and they show us exactly what happened.

TO STOP OR REMOVE
  Stop, keeping your data:  run your START-HERE file with  --stop
  Remove everything:        run it with  --uninstall
--uninstall DELETES every document you added. It asks before doing it.
