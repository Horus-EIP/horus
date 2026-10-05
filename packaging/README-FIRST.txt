HORUS - BETA TEST BUILD
=======================
BEFORE YOU START you need Docker Desktop installed AND RUNNING
(https://www.docker.com/products/docker-desktop/), Python 3.11+
(https://www.python.org/downloads/), 150 GB free disk, and internet.
With an NVIDIA GPU 125 GB is enough.

YOUR ACCESS TOKEN
Horus downloads its own containers from our private registry. Save
the access token we sent you as  registry-token.txt  in this folder,
on one line:  USERNAME:TOKEN
It never goes into install-log.txt. Do not send that file to anyone.

TO INSTALL
  Windows  double-click  START-HERE-Windows.bat
  macOS    RIGHT-CLICK   START-HERE-macOS.command  and choose Open
  Linux    run           ./START-HERE-Linux.sh
It asks two or three questions, then downloads and starts everything.
Our containers come prebuilt and signed: nothing is built on your
machine. When testers built them, the first run took 1.5 to 2 hours;
downloading them instead has not been timed yet. Then it downloads an
AI model. It is NOT frozen. Leave it running and it will finish. A
download that fails is retried automatically, and an interrupted one
resumes where it stopped when you run it again.

ABOUT THE DISK SPACE
150 GB is the peak we measured when the containers were built on the
tester's machine. Downloading them should need less, but until we have
measured it the installer still asks for 150 GB.

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
