from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path

from common import (
    EXIT_CONSENT_CANCELLED,
    EXIT_USAGE,
    InstallError,
    Log,
    bold,
    dim,
    red,
    rule,
    yellow,
)

CONSENT_DEMO = "demo"
CONSENT_FOLDERS = "folders"
CONSENT_WHOLE_DEVICE = "whole-device"
VALID_MODES = (CONSENT_DEMO, CONSENT_FOLDERS, CONSENT_WHOLE_DEVICE)

WHOLE_DEVICE_PHRASE = "I ACCEPT FULL DISK ACCESS"

HORUS_CORPUS_ENV_KEY = "HORUS_CORPUS_DIR"
DEMO_CORPUS_DIR = "../../demo_assets"
CONTAINER_CORPUS_PATH = "/app/corpus"

TREE = "tree"
SELF = "self"

FORBIDDEN_POSIX = (
    ("/", SELF),
    ("/etc", TREE),
    ("/usr", TREE),
    ("/bin", TREE),
    ("/sbin", TREE),
    ("/lib", TREE),
    ("/var", TREE),
    ("/run", TREE),
    ("/boot", TREE),
    ("/dev", TREE),
    ("/proc", TREE),
    ("/sys", TREE),
    ("/srv", TREE),
    ("/snap", TREE),
    ("/home", TREE),
    ("/Users", TREE),
    ("/System", TREE),
    ("/Library", TREE),
    ("/Applications", TREE),
    ("/private", TREE),
    ("/opt/homebrew", TREE),
)

WINDOWS_ENV_ROOTS = (
    "SystemRoot",
    "windir",
    "ProgramFiles",
    "ProgramFiles(x86)",
    "ProgramW6432",
    "ProgramData",
    "PUBLIC",
)
WINDOWS_LITERAL_ROOTS = (
    "Windows",
    "Program Files",
    "Program Files (x86)",
    "ProgramData",
    "Users",
    "Recovery",
    "$Recycle.Bin",
    "System Volume Information",
)

WINDOWS_DIRS_VIA_MOUNT = {
    "windows": TREE,
    "program files": TREE,
    "program files (x86)": TREE,
    "programdata": TREE,
    "recovery": TREE,
    "$recycle.bin": TREE,
    "system volume information": TREE,
    "users": SELF,
}

DEVICE_PREFIXES = ("\\\\?\\", "\\\\.\\")
_UNC_MARKER = "UNC\\"

COMPOSE_UNSAFE = "#$\"'\n\r"
COMPOSE_UNSAFE_POSIX = ":"

CHAR_NAMES = {
    "\n": "a line break",
    "\r": "a carriage return",
}


class PathRejected(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def strip_device_prefix(path: Path) -> Path:
    if os.name != "nt":
        return path
    text = str(path)
    for prefix in DEVICE_PREFIXES:
        if not text.startswith(prefix):
            continue
        rest = text[len(prefix) :]
        if rest[: len(_UNC_MARKER)].upper() == _UNC_MARKER:
            return Path("\\\\" + rest[len(_UNC_MARKER) :])
        return Path(rest)
    return path


def _is_mount_point(path: Path) -> bool:
    try:
        return os.path.ismount(path)
    except OSError:
        return False


def _immediate_subdirs(path: Path) -> list[Path]:
    try:
        return [child for child in path.iterdir() if child.is_dir()]
    except OSError:
        return []


def _windows_dir_via_mount(resolved: Path) -> str | None:
    parts = resolved.parts
    for depth in range(len(parts) - 1, 0, -1):
        if not _is_mount_point(Path(*parts[:depth])):
            continue
        rest = parts[depth:]
        if not rest:
            return None
        kind = WINDOWS_DIRS_VIA_MOUNT.get(rest[0].lower())
        if kind is None:
            return None
        if kind == SELF and len(rest) > 1:
            return None
        return str(Path(*parts[: depth + 1]))
    return None


def _home() -> Path:
    try:
        return Path.home().resolve()
    except (RuntimeError, OSError):  # pragma: no cover - no HOME set anywhere
        return Path(os.path.expanduser("~")).absolute()


def _drive_roots() -> list[Path]:
    roots: list[Path] = []
    candidates = [os.environ.get("SystemDrive", "C:") + "\\", str(_home().anchor)]
    for var in WINDOWS_ENV_ROOTS:
        val = os.environ.get(var)
        if val:
            candidates.append(str(Path(val).anchor))
    for raw in candidates:
        if not raw:
            continue
        p = Path(raw)
        if p not in roots:
            roots.append(p)
    return roots


def forbidden_roots() -> list[tuple[Path, str]]:
    raw: list[tuple[Path, str]] = []
    if os.name == "nt":
        for var in WINDOWS_ENV_ROOTS:
            val = os.environ.get(var)
            if val:
                raw.append((Path(val), TREE))
        for drive in _drive_roots():
            for name in WINDOWS_LITERAL_ROOTS:
                raw.append((drive / name, TREE))
    else:
        raw.extend((Path(p), kind) for p, kind in FORBIDDEN_POSIX)

    profile_tree = _home().parent
    if profile_tree != profile_tree.parent:
        raw.append((profile_tree, TREE))

    raw.append((_home(), SELF))

    out: list[tuple[Path, str]] = []
    seen: set[tuple[str, str]] = set()
    for path, kind in raw:
        try:
            resolved = path.resolve()
        except OSError:  # pragma: no cover - unreadable mount point
            resolved = path
        resolved = strip_device_prefix(resolved)
        key = (str(resolved).lower() if os.name == "nt" else str(resolved), kind)
        if key in seen:
            continue
        seen.add(key)
        out.append((resolved, kind))
    return out


def system_location_reason(resolved: Path) -> str | None:
    if resolved.parent == resolved:
        return "that is a whole drive / filesystem root"

    if os.name != "nt" and _is_mount_point(resolved):
        return (
            "that is the top of a mounted filesystem - a whole device by "
            "another name; pick a folder inside it, or choose option 3 if "
            "you really do mean the whole device"
        )

    if os.name != "nt":
        for child in _immediate_subdirs(resolved):
            if _is_mount_point(child):
                return (
                    f"that folder contains {child}, the top of a mounted "
                    "filesystem - granting it would hand over that whole "
                    "device; pick a folder inside it, or choose option 3 "
                    "if you really do mean a whole device"
                )

        windows_dir = _windows_dir_via_mount(resolved)
        if windows_dir:
            return (
                f"{windows_dir} is a Windows system location reached "
                "through a mounted drive - the same folder your Windows "
                "side would refuse; pick a folder inside your own "
                "profile instead"
            )

    home = _home()
    inside_own_home = home in resolved.parents

    if resolved == home:
        return (
            "that is your entire home directory - a folder inside it "
            "is fine, the whole thing is not"
        )

    table = forbidden_roots()

    for root, _kind in table:
        if resolved == root:
            return f"{root} is a system location"

    for root, kind in table:
        if resolved in root.parents:
            return f"it contains the system location {root}"
        if kind == TREE and root in resolved.parents:
            if inside_own_home and root in home.parents:
                continue
            return f"it is inside the system location {root}"
    return None


def validate_folder(raw: str) -> Path:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    if not text:
        raise PathRejected("that was empty")

    candidate = Path(os.path.expanduser(text))
    if not candidate.is_absolute():
        example = "C:\\Users\\you\\Documents\\reports" if os.name == "nt" else "/home/you/reports"
        raise PathRejected(
            f"that is not an absolute path (it must start from the top, e.g. {example})"
        )
    if not candidate.exists():
        raise PathRejected("there is nothing at that path (check the spelling)")
    if not candidate.is_dir():
        raise PathRejected("that is a file, not a folder - give the folder that contains it")

    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise PathRejected(f"the path could not be resolved ({exc.strerror or exc})") from exc

    resolved = strip_device_prefix(resolved)

    if resolved.drive.startswith("\\\\") or not resolved.is_absolute():
        raise PathRejected(
            "that is a network or device path (a UNC share) - give a normal "
            "local path instead, e.g. C:\\Users\\you\\Documents\\reports"
        )

    try:
        with os.scandir(resolved) as it:
            next(iter(it), None)
    except PermissionError:
        raise PathRejected("you do not have permission to read that folder") from None
    except OSError as exc:
        raise PathRejected(f"that folder could not be read ({exc.strerror or exc})") from None

    reason = system_location_reason(resolved)
    if reason is not None:
        raise PathRejected(reason)

    unsafe = COMPOSE_UNSAFE + ("" if os.name == "nt" else COMPOSE_UNSAFE_POSIX)
    found = [c for c in unsafe if c in str(resolved)]
    if found:
        names = ", ".join(CHAR_NAMES.get(c, c) for c in found)
        raise PathRejected(
            f"that path contains {names} - Docker Compose re-reads the path out "
            "of .env and would mount a different folder; rename it or pick "
            "another folder"
        )
    for part in resolved.parts:
        if part != part.strip():
            raise PathRejected(
                f"the folder name {part!r} begins or ends with a space - .env "
                "does not carry that through, so a different folder would be "
                "mounted; rename it or pick another folder"
            )
    return resolved


def add_folder(accepted: list[Path], candidate: Path) -> None:
    for existing in accepted:
        if existing == candidate:
            raise PathRejected("you already added that folder")
        if existing in candidate.parents:
            raise PathRejected(f"that is already covered by {existing}")
        if candidate in existing.parents:
            raise PathRejected(
                f"that contains {existing}, which you already added - "
                "add one or the other, not both"
            )
    accepted.append(candidate)


def to_compose_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def whole_device_root() -> Path:
    if os.name == "nt":
        return Path(_home().anchor or os.environ.get("SystemDrive", "C:") + "\\")
    return Path("/")


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _choice(mode: str, paths: list[Path], corpus_dir: str) -> dict:
    return {
        "mode": mode,
        "paths": [str(p) for p in paths],
        "corpus_dir": corpus_dir,
        "accepted_at": _now_iso(),
    }


def demo_choice(repo: Path) -> dict:
    return _choice(CONSENT_DEMO, [repo / "demo_assets"], DEMO_CORPUS_DIR)


def describe(choice: dict) -> str:
    mode = choice.get("mode")
    corpus = choice.get("corpus_dir", "")
    paths = choice.get("paths") or []
    when = choice.get("accepted_at", "")

    if mode == CONSENT_DEMO:
        head = "Demo corpus only - nothing outside the Horus folder is exposed."
    elif mode == CONSENT_FOLDERS:
        head = f"One folder you chose is exposed, read-only:  {paths[0] if paths else '?'}"
    elif mode == CONSENT_WHOLE_DEVICE:
        head = f"WHOLE DEVICE exposed, read-only:  {paths[0] if paths else '?'}"
    else:
        head = f"unknown consent mode {mode!r}"

    return (
        f"{head}\n"
        f"  mount        {corpus} -> {CONTAINER_CORPUS_PATH}  (read-only)\n"
        f"  .env         {HORUS_CORPUS_ENV_KEY}={corpus}\n"
        f"  accepted at  {when}"
    )


_MENU = """
  1) Bundled demo corpus only            (default, recommended)
     Five short example documents that ship with Horus. Nothing outside
     the Horus folder is mounted.

  2) A folder you choose
     One folder on this machine, mounted read-only. Everything in it,
     including sub-folders, gets indexed.

  3) The entire device
     Everything readable on this machine. Requires a typed confirmation.
"""


def _stdin_is_interactive() -> bool:
    try:
        return bool(sys.stdin) and sys.stdin.isatty()
    except (ValueError, AttributeError):
        return False


def _prompt(log: Log, input_fn, text: str) -> str:
    try:
        answer = input_fn(text)
    except EOFError:
        raise InstallError(
            EXIT_CONSENT_CANCELLED,
            "Install cancelled: no answer to the data-access question.",
            "Input ended while waiting for a consent choice, so nothing was\n"
            "installed and no folder was shared.",
            "Run the START-HERE launcher again from a normal terminal window.\n"
            "For an unattended run, the demo corpus is used automatically:\n"
            "  START-HERE (your platform) --yes",
        ) from None
    log.debug(f"consent prompt {text.strip()!r} -> {answer.strip()!r}")
    return answer


def _ask_folder(log: Log, input_fn) -> list[Path]:
    log.say("")
    log.say("  Type an absolute path to a folder, then Enter.")
    log.say("  Add more if you like; press Enter on an empty line when done.")
    log.say(dim("  Everything inside it is indexed and can be quoted back in an answer."))
    log.say(dim("  It is mounted read-only: Horus can never modify or delete it."))

    accepted: list[Path] = []
    while True:
        raw = _prompt(log, input_fn, "\n  folder> ")
        if not raw.strip():
            if accepted:
                break
            log.warn("No folder given yet. Type a path, or type 'back' for the menu.")
            continue
        if raw.strip().lower() in ("back", "b", "cancel"):
            return []
        try:
            folder = validate_folder(raw)
            add_folder(accepted, folder)
        except PathRejected as exc:
            log.fail(f"Not usable: {exc.reason}")
            continue
        log.ok(f"will mount read-only: {folder}")

    if len(accepted) == 1:
        return accepted

    log.say("")
    log.warn("Horus mounts exactly one folder per install.")
    log.say("  " + dim("The container has a single /app/corpus directory, so one install"))
    log.say("  " + dim("indexes one folder. Pick the one to use now; you can re-run the"))
    log.say("  " + dim("installer later to point Horus at a different folder."))
    log.say("")
    for i, folder in enumerate(accepted, 1):
        log.say(f"    {i}) {folder}")
    while True:
        raw = _prompt(log, input_fn, f"\n  which one? [1-{len(accepted)}, default 1] ")
        text = raw.strip()
        if not text:
            return [accepted[0]]
        if text.isdigit() and 1 <= int(text) <= len(accepted):
            return [accepted[int(text) - 1]]
        log.fail(f"Type a number between 1 and {len(accepted)}.")


def _ask_whole_device(log: Log, input_fn) -> bool:
    root = whole_device_root()
    log.say("")
    log.say(red(rule("READ THIS BEFORE YOU AGREE")))
    log.say("")
    log.say("  You are about to let Horus read every file it can reach under")
    log.say(f"  {root} - including, if they are there:")
    log.say("")
    log.say("    - SSH private keys and cloud credentials (~/.ssh, ~/.aws)")
    log.say("    - browser profiles, cookies and saved passwords")
    log.say("    - password-manager exports")
    log.say("    - tax documents, payslips, bank statements")
    log.say("    - medical records")
    log.say("    - source code with API keys and tokens committed in it")
    log.say("")
    log.say(bold("  Anything the RAG pipeline can read, it will index."))
    log.say(bold("  Once indexed, an agent can quote it back inside an answer."))
    log.say("")
    log.say("  The mount is read-only, so your files cannot be changed or deleted,")
    log.say("  but they CAN be read, embedded, and repeated back to you.")
    if os.name == "nt":
        log.say("")
        log.say(dim(f"  (This shares the {root} drive. Other drives are not included.)"))
    log.say("")
    log.say("  Option 2 - a single folder - does everything the beta needs.")
    log.say("")
    log.say(yellow(f"  To continue, type this exactly:   {WHOLE_DEVICE_PHRASE}"))
    log.say(dim("  Anything else takes you back to the menu."))

    typed = _prompt(log, input_fn, "\n  phrase> ")
    if typed.strip() == WHOLE_DEVICE_PHRASE:
        log.warn(f"Whole-device access GRANTED at {_now_iso()} (read-only).")
        return True
    log.say("")
    log.ok("Phrase did not match. Whole-device access NOT granted.")
    return False


def choose(
    log: Log,
    repo: Path,
    non_interactive: bool = False,
    preselect: str | None = None,
    *,
    input_fn=None,
    interactive: bool | None = None,
) -> dict:
    if preselect is not None and preselect not in VALID_MODES:
        raise InstallError(
            EXIT_USAGE,
            f"Unknown --consent value: {preselect!r}",
            "Valid values are:  " + ", ".join(VALID_MODES),
            "Re-run with one of the values above, or leave --consent off and\n"
            "answer the question when it is asked.",
        )

    input_fn = input_fn or input
    if interactive is None:
        interactive = _stdin_is_interactive()

    if non_interactive or not interactive:
        if preselect == CONSENT_WHOLE_DEVICE:
            log.warn(
                "--consent=whole-device needs a person to type the confirmation "
                "phrase; there is no terminal here."
            )
        elif preselect == CONSENT_FOLDERS:
            log.warn(
                "--consent=folders needs a person to type a folder path; there is no terminal here."
            )
        choice = demo_choice(repo)
        log.info(f"consent: non-interactive, defaulted to {CONSENT_DEMO}")
        log.ok("Data access: bundled demo corpus only (unattended run).")
        return choice

    log.say("")
    log.say(bold("  What should Horus be allowed to read?"))
    log.say("")
    log.say("  Horus indexes documents so agents can answer questions about them.")
    log.say("  Whatever you point it at is mounted READ-ONLY - it is never modified.")
    log.say(_MENU)
    if preselect:
        log.say(dim(f"  (--consent={preselect} was passed; it is offered as the default.)"))

    default_key = {CONSENT_DEMO: "1", CONSENT_FOLDERS: "2", CONSENT_WHOLE_DEVICE: "3"}.get(
        preselect or CONSENT_DEMO, "1"
    )

    while True:
        raw = _prompt(
            log, input_fn, f"  Choose 1, 2 or 3 [default {default_key}], or q to cancel: "
        )
        answer = raw.strip().lower() or default_key

        if answer in ("q", "quit", "cancel"):
            raise InstallError(
                EXIT_CONSENT_CANCELLED,
                "Install cancelled at the data-access question.",
                "Nothing was installed and no folder was shared.",
                "Run the START-HERE launcher again whenever you are ready.\n"
                "Choosing option 1 shares nothing outside the Horus folder.",
            )

        if answer == "1":
            choice = demo_choice(repo)
            demo = repo / "demo_assets"
            if not demo.is_dir():
                log.warn(
                    f"Expected demo documents at {demo} but that folder is missing; "
                    "chat will work, document questions will not."
                )
            log.ok("Data access: bundled demo corpus only.")
            log.info(f"consent: {CONSENT_DEMO} at {choice['accepted_at']}")
            return choice

        if answer == "2":
            folders = _ask_folder(log, input_fn)
            if not folders:
                log.say("")
                continue
            folder = folders[0]
            choice = _choice(CONSENT_FOLDERS, [folder], to_compose_path(folder))
            log.ok(f"Data access: {folder} (read-only)")
            log.info(f"consent: {CONSENT_FOLDERS} -> {folder} at {choice['accepted_at']}")
            return choice

        if answer == "3":
            if _ask_whole_device(log, input_fn):
                root = whole_device_root()
                choice = _choice(CONSENT_WHOLE_DEVICE, [root], to_compose_path(root))
                log.info(
                    f"consent: {CONSENT_WHOLE_DEVICE} -> {root} at {choice['accepted_at']} "
                    f"(phrase typed exactly)"
                )
                return choice
            log.say("")
            continue

        log.fail("Type 1, 2 or 3 (or q to cancel).")
