import pytest

import ghpypi


@pytest.mark.parametrize(
    "arguments",
    (
        [],
        ["--token", "asdf", "--token-stdin"],
        ["--token-stdin"],
        ["--token", "asdf"],
        ["--token", "asdf", "--output", "/path/to/nowhere"],
        ["--token", "asdf", "--repositories", "/path/to/nowhere.txt"],
    ),
)
def test_parse_arguments(arguments):
    with pytest.raises(SystemExit):
        ghpypi.parse_arguments(arguments)


def test_valid_values():
    x = ghpypi.parse_arguments(
        [
            "--token-stdin",
            "--output",
            "/path/to/output",
            "--repositories",
            "/path/to/repos.txt",
        ],
    )
    assert not x.verbose
    assert x.title == "My Private PyPI"
    assert x.output == "/path/to/output"
    assert x.repositories == "/path/to/repos.txt"
    assert x.token_stdin
    assert x.token is None

    x = ghpypi.parse_arguments(
        [
            "--token",
            "asdf",
            "--output",
            "/path/to/output",
            "--repositories",
            "/path/to/repos.txt",
        ],
    )
    assert not x.verbose
    assert x.title == "My Private PyPI"
    assert x.output == "/path/to/output"
    assert x.repositories == "/path/to/repos.txt"
    assert not x.token_stdin
    assert x.token == "asdf"  # noqa: S105
