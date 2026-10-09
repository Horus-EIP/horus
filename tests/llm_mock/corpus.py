import sys

from clients import REPO

DEMO = REPO / "demo_assets"
CHUNK_CHARS = 1000

sys.path.insert(0, str(REPO / "installer"))
import smoke  # noqa: E402


def demo_chunks(titles=None) -> list[tuple[str, str]]:
    chunks = []
    for path in sorted(DEMO.glob("*.md")):
        if titles is not None and path.name not in titles:
            continue
        lines, size = [], 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if lines and size + len(line) > CHUNK_CHARS:
                chunks.append((path.name, "\n".join(lines)))
                lines, size = [], 0
            lines.append(line)
            size += len(line) + 1
        if lines:
            chunks.append((path.name, "\n".join(lines)))
    return chunks


def demo_context(titles=None, header="[S{n}] {title}") -> tuple[str, tuple[str, ...]]:
    chunks = demo_chunks(titles)
    blocks = [f"{header.format(n=n, title=title)}\n{text}" for n, (title, text) in enumerate(chunks, 1)]
    return "\n\n".join(blocks), tuple(f"S{n}" for n in range(1, len(chunks) + 1))
