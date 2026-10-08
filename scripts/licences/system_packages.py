from __future__ import annotations

import io
import re
import subprocess
import tarfile
from pathlib import Path

DEBIAN_LIST = r"dpkg-query -W -f='${Package}\t${Version}\t${source:Package}\t${source:Version}\n'"
DEBIAN_COPYRIGHTS = "cd /usr/share/doc && tar -chf - */copyright 2>/dev/null; true"
ALPINE_DB = "cat /lib/apk/db/installed"
DETECT = "if [ -f /lib/apk/db/installed ]; then echo alpine; else echo debian; fi; cat /etc/os-release"
DEP5 = re.compile(r"^Format:\s*\S*(copyright-format|dep5|DEP-5)", re.M | re.I)
GPL_WORDS = re.compile(r"GNU General Public License|common-licenses/GPL|\bGPL\b|\bGPL-?[123v]", re.I)
LGPL_WORDS = re.compile(r"GNU (Lesser|Library) General Public License|common-licenses/LGPL|\bLGPL", re.I)
FIELD = re.compile(r"^([A-Za-z-]+):\s*(.*)$")
TOKEN_SPLIT = re.compile(r"\s+(?:and|or)\s+|\s*[,|()]\s*", re.I)
SPDX_LIKE = re.compile(r"^(L?GPL)-?(\d)(?:\.(\d))?(\+|-or-later)?", re.I)
INSTALL = re.compile(r"(?:apt-get|apt)\s+install\s+(.*?)(?:&&|;|$)|apk\s+add\s+(.*?)(?:&&|;|$)")


def run(image: str, script: str) -> bytes:
    return subprocess.run(
        ["docker", "run", "--rm", "--user", "0", "--network", "none", "--entrypoint", "sh", image, "-c", script],
        capture_output=True, check=True,
    ).stdout


def family(token: str) -> str:
    low = token.strip().lower()
    if re.search(r"\blgpl|lesser general|library general", low):
        return "LGPL"
    if re.search(r"\bgpl|general public license", low):
        return "GPL"
    return "other"


def classify(expression: str) -> str:
    expression = re.sub(r"\s+with\s+.*?exception\S*", "", expression, flags=re.I)
    if re.search(r"\s+and\s+", expression, flags=re.I):
        kinds = {classify(part) for part in re.split(r"\s+and\s+", expression, flags=re.I)}
        return next((kind for kind in ("GPL", "LGPL", "choice") if kind in kinds), "other")
    families = [family(part) for part in re.split(r"\s+or\s+|\s*\|\s*", expression, flags=re.I)]
    if all(found == "other" for found in families):
        return "other"
    if "other" in families:
        return "choice"
    return "GPL" if "GPL" in families else "LGPL"


def copyleft_tokens(expressions: list[str]) -> list[str]:
    tokens = []
    for expression in expressions:
        for part in TOKEN_SPLIT.split(expression):
            part = part.strip()
            if part and family(part) != "other" and part not in tokens:
                tokens.append(part)
    return sorted(tokens, key=str.lower)


def paragraphs(text: str) -> list[dict[str, str]]:
    found = []
    for block in re.split(r"\n\s*\n", text):
        fields: dict[str, str] = {}
        key = None
        for line in block.splitlines():
            match = FIELD.match(line)
            if match and not line.startswith((" ", "\t")):
                key = match.group(1).lower()
                fields[key] = match.group(2).strip()
            elif key == "files" and line.startswith((" ", "\t")):
                fields[key] += " " + line.strip()
        if fields:
            found.append(fields)
    return found


def debian_licences(text: str) -> list[str]:
    if not DEP5.search(text):
        stripped = re.sub(r"GNU (Lesser|Library) General Public License|LGPL[-\w.+]*|common-licenses/LGPL\S*",
                          "", text, flags=re.I)
        return [name for name, found in (("GPL", GPL_WORDS.search(stripped)), ("LGPL", LGPL_WORDS.search(text)))
                if found]
    copyleft, main = [], False
    for paragraph in paragraphs(text):
        files = paragraph.get("files", "").split()
        licence = paragraph.get("license", "")
        if not files or not licence or all(name == "debian" or name.startswith("debian/") for name in files):
            continue
        if classify(licence) in ("GPL", "LGPL"):
            copyleft.append(licence)
            main = main or files == ["*"]
    if not main and copyleft and all("exception" in licence.lower() for licence in copyleft):
        return []
    return copyleft_tokens(copyleft)


def alpine_licences(expression: str) -> list[str]:
    return copyleft_tokens([expression]) if classify(expression) in ("GPL", "LGPL") else []


def spdx_texts(licences: list[str]) -> list[str]:
    found = set()
    for licence in licences:
        match = SPDX_LIKE.match(licence.strip())
        if match:
            prefix, major, minor, later = match.groups()
            found.add(f"{prefix.upper()}-{major}.{minor or 0}-{'or-later' if later else 'only'}")
    return sorted(found)


def os_field(release: str, name: str) -> str:
    match = re.search(rf'^{name}="?([^"\n]*)"?', release, re.M)
    return match.group(1) if match else ""


def image_packages(image: str, overrides: dict[str, dict]) -> tuple[dict, list[str]]:
    detected = run(image, DETECT).decode("utf-8", "replace")
    kind, _, release = detected.partition("\n")
    problems: list[str] = []
    rows = alpine_rows(image) if kind.strip() == "alpine" else debian_rows(image, overrides, problems)
    return {"os": os_field(release, "PRETTY_NAME"), "os_version": os_field(release, "VERSION_ID"),
            "kind": kind.strip(), "packages": rows}, problems


def debian_rows(image: str, overrides: dict[str, dict], problems: list[str]) -> list[dict]:
    texts = {}
    with tarfile.open(fileobj=io.BytesIO(run(image, DEBIAN_COPYRIGHTS))) as archive:
        for member in archive.getmembers():
            if (member.isfile() or member.islnk()) and member.name.endswith("/copyright"):
                texts[member.name.split("/")[-2]] = archive.extractfile(member).read().decode("utf-8", "replace")
    rows = []
    for line in run(image, DEBIAN_LIST).decode("utf-8", "replace").splitlines():
        name, version, source, source_version = (line.split("\t") + [""] * 4)[:4]
        source, source_version = source or name, source_version or version
        if source in overrides:
            shown = overrides[source].get("licence") or ""
            licences = copyleft_tokens([shown])
        elif name in texts:
            licences = debian_licences(texts[name])
            shown = ", ".join(licences)
        else:
            problems.append(f"{image}: {name} {version} has no copyright file; add its source {source} "
                            "to system_overrides in components.yaml")
            continue
        if licences:
            rows.append({"name": name, "version": version, "source": source, "source_version": source_version,
                         "licence": shown, "texts": spdx_texts(licences)})
    return sorted(rows, key=lambda row: row["name"])


def alpine_rows(image: str) -> list[dict]:
    rows, current = [], {}
    for line in run(image, ALPINE_DB).decode("utf-8", "replace").splitlines() + [""]:
        if line[1:2] == ":":
            current.setdefault(line[0], line[2:])
            continue
        licences = alpine_licences(current.get("L", "")) if current else []
        if licences:
            rows.append({"name": current["P"], "version": current["V"], "source": current.get("o") or current["P"],
                         "source_version": current["V"], "commit": current.get("c", ""),
                         "licence": ", ".join(licences), "texts": spdx_texts(licences)})
        current = {}
    return sorted(rows, key=lambda row: row["name"])


def logical_lines(dockerfile: Path) -> list[str]:
    lines, pending = [], ""
    for raw in dockerfile.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        pending += " " + stripped.rstrip("\\").strip()
        if not stripped.endswith("\\"):
            lines.append(pending.strip())
            pending = ""
    return lines + ([pending.strip()] if pending else [])


def recipe(dockerfile: Path) -> dict:
    lines = logical_lines(dockerfile)
    start = max(index for index, line in enumerate(lines) if line.upper().startswith("FROM "))
    installs = set()
    for line in lines[start + 1:]:
        if line.upper().startswith("RUN "):
            for apt, apk in INSTALL.findall(line):
                installs.update(word for word in (apt or apk).split() if not word.startswith("-"))
    return {"from": lines[start].split()[1], "installs": sorted(installs)}
