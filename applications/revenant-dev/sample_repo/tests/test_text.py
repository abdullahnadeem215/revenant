from sample_pkg.text import slugify


def test_slugify_spaces() -> None:
    assert slugify("Hello World") == "hello-world"


def test_slugify_lowercases() -> None:
    assert slugify("ABC") == "abc"
