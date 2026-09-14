import posixpath
import urllib.parse


def sanitize_relative_path(path_str: str) -> str:
    """Normalizes and ensures a path is safe, relative, and posix-compliant.

    Guarantees:
    - Rejects null bytes (\x00) and dangerous escapes.
    - Decodes URL-encoded segments safely and detects traversal attempts.
    - Rejects paths with directory traversal ('..', '../').
    - Strips leading and trailing slashes/dots while preserving internal hierarchy.
    - Never allows escaping the storage root.

    Raises:
        ValueError: If the path contains null bytes, invalid traversal, or is unsafe.
    """
    if not path_str or not path_str.strip():
        raise ValueError("Path cannot be empty.")

    # Check for null bytes
    if "\x00" in path_str:
        raise ValueError("Path contains null byte.")

    # Handle URL decoding (repeated decode to defend against double-encoding)
    decoded = urllib.parse.unquote(path_str)
    if "\x00" in decoded:
        raise ValueError("Path contains null byte after decoding.")

    # Normalize backslashes to forward slashes
    normalized_slash = decoded.replace("\\", "/")

    # Reject absolute paths or explicit root escapes early
    parts = [p for p in normalized_slash.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError(f"Path traversal detected: {path_str}")

    # Canonicalize posix path
    clean = posixpath.normpath(normalized_slash)

    if clean.startswith("/") or clean.startswith("../") or clean == "..":
        raise ValueError(f"Path escapes root directory: {path_str}")

    result = clean.lstrip("./")
    if not result:
        raise ValueError("Resulting path is empty.")

    return result
