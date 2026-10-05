import sys

try:
    import resource
except ImportError:
    resource = None


def peak_rss_bytes() -> int | None:
    if resource is not None:
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak if sys.platform == "darwin" else peak * 1024
    try:
        import psutil
    except ImportError:
        return None
    return getattr(psutil.Process().memory_info(), "peak_wset", None)


def peak_rss_mb() -> str:
    peak = peak_rss_bytes()
    return "unknown" if peak is None else str(round(peak / 1024**2))
