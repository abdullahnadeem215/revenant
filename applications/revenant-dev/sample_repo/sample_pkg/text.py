"""Text helpers."""


def slugify(title: str) -> str:
    """Lowercase title and join its words with hyphens."""
    return "-".join(title.lower().split())
