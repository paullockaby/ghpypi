import io
import os
from pathlib import PosixPath

import github
import pytest
from pytest_mock import MockerFixture

from ghpypi import ghpypi


@pytest.mark.parametrize(("package_name", "version"), (
    ("completely invalid package", "0.0.0"),
    ("ghpypi", "0.0.0"),
    ("pytest", pytest.__version__),
))
def test_get_version(package_name: str, version: str):
    assert ghpypi.get_version(package_name) == version


@pytest.mark.parametrize(("file_name", "cleaned"), (
    ("foo.bar", "foo"),
    ("mypackage.whl", "mypackage"),
    ("mypackage.whatever.whl", "mypackage.whatever"),
    ("mypackage.tar.gz", "mypackage"),
    ("mypackage.tar.bz2", "mypackage"),
    ("mypackage.tar.xz", "mypackage"),
    ("mypackage.gz", "mypackage"),
    ("mypackage.bz2", "mypackage"),
    ("mypackage.xz", "mypackage"),
    ("mypackage.asdf", "mypackage"),
))
def test_remove_extension(file_name: str, cleaned: str):
    assert ghpypi.remove_package_extension(file_name) == cleaned


@pytest.mark.parametrize(("file_name", "name", "version"), (
    # wheels
    ("dumb_init-1.2.0-py2.py3-none-manylinux1_x86_64.whl", "dumb_init", "1.2.0"),
    ("ocflib-2016.12.10.1.48-py2.py3-none-any.whl", "ocflib", "2016.12.10.1.48"),
    ("aspy.yaml-0.2.2-py2.py3-none-any.whl", "aspy.yaml", "0.2.2"),
    (
        "numpy-1.11.1rc1-cp27-cp27m-macosx_10_6_intel.macosx_10_9_intel.macosx_10_9_x86_64.macosx_10_10_intel.macosx_10_10_x86_64.whl",  # noqa
        "numpy",
        "1.11.1rc1",
    ),

    # other stuff
    ("aspy.yaml.zip", "aspy.yaml", None),
    ("ocflib-3-4.tar.gz", "ocflib-3-4", None),
    ("aspy.yaml-0.2.1.tar.gz", "aspy.yaml", "0.2.1"),
    ("numpy-1.11.0rc1.tar.gz", "numpy", "1.11.0rc1"),
    ("pandas-0.2beta.tar.gz", "pandas", "0.2beta"),
    ("scikit-learn-0.15.1.tar.gz", "scikit-learn", "0.15.1"),
    ("ocflib-2015.11.23.20.2.tar.gz", "ocflib", "2015.11.23.20.2"),
    ("mesos.cli-0.1.3-py2.7.egg", "mesos.cli", "0.1.3-py2.7"),

    # inspired by pypiserver"s tests
    ("flup-123-1.0.3.dev-20110405.tar.gz", "flup-123", "1.0.3.dev-20110405"),
    ("package-123-1.3.7+build.11.e0f985a.zip", "package-123", "1.3.7+build.11.e0f985a"),
))
def test_guess_name_version_from_filename(file_name: str, name: str, version: str):
    assert ghpypi.guess_name_version_from_filename(file_name) == (name, version)


@pytest.mark.parametrize(("file_name", "name", "version"), (
    ("dumb-init-0.1.0.linux-x86_64.tar.gz", "dumb-init", "0.1.0"),
    ("greenlet-0.3.4-py3.1-win-amd64.egg", "greenlet", "0.3.4"),
    ("numpy-1.7.0.win32-py3.1.exe", "numpy", "1.7.0"),
    ("surf.sesame2-0.2.1_r291-py2.5.egg", "surf.sesame2", "0.2.1_r291"),
))
def test_guess_name_version_from_filename_only_name(file_name: str, name: str, version: str):
    """Broken version check tests.
    The real important thing is to be able to parse the name, but it's nice if
    we can parse the versions too. Unfortunately, we can't yet for these cases.
    """
    parsed_name, parsed_version = ghpypi.guess_name_version_from_filename(file_name)
    assert parsed_name == name

    # If you can make this assertion fail, great! Move it up above!
    assert parsed_version != version


@pytest.mark.parametrize("file_name", (
    "",
    "lol",
    "lol-sup",
    "-20160920.193125.zip",
    "playlyfe-0.1.1-2.7.6-none-any.whl",  # 2.7.6 is not a valid python tag
))
def test_guess_name_version_from_filename_invalid(file_name: str):
    with pytest.raises(ValueError):
        ghpypi.guess_name_version_from_filename(file_name)


def test_load_repositories(tmp_path: PosixPath):
    tmp_data = tmp_path / "repos.txt"
    tmp_data.write_text("""

        # this is a comment
        foo/bar
        baz/bat
    """)

    tmp_data_path = str(tmp_data)
    repos = ghpypi.load_repositories(tmp_data_path)
    result = list(repos)
    assert len(result) == 2
    assert result[0] == ghpypi.Repository("foo", "bar")
    assert result[1] == ghpypi.Repository("baz", "bat")


@pytest.mark.parametrize("data", (
    "some invalid data",
    "; this is invalid",
    "foo/bar/asdf",
    "baz/",
    "bat",
    "/battery",
))
# using the "tmp_path" argument MAGICALLY gives us a temporary directory to put things *eye roll*
def test_load_bad_repositories(tmp_path: PosixPath, data: str):
    tmp_data = tmp_path / "repos.txt"
    tmp_data.write_text(data)

    tmp_data_path = str(tmp_data)
    with pytest.raises(ValueError):
        list(ghpypi.load_repositories(tmp_data_path))


def test_github_tokens(mocker: MockerFixture):
    # save the original environment before we use it
    original_environ = os.environ.get

    # make calls to get GITHUB_TOKEN return None
    mocker.patch("os.environ.get", lambda key: None if key == "GITHUB_TOKEN" else original_environ(key))

    # token provided, do not read from stdin
    assert ghpypi.get_github_token("foo", False) == "foo"

    # token provided, DO read from stdin which we will ignore
    assert ghpypi.get_github_token("foo", True) == "foo"

    # no token provided, do not read from stdin, environment empty
    with pytest.raises(ValueError):
        ghpypi.get_github_token(None, False)

    # no token provided, do not read from stdin, environment empty
    with pytest.raises(ValueError):
        ghpypi.get_github_token("", False)

    # token provided on stdin
    mocker.patch("sys.stdin", io.StringIO("foobarbazbat"))
    assert ghpypi.get_github_token(None, True) == "foobarbazbat"

    # token provided on stdin but it is blank
    mocker.patch("sys.stdin", io.StringIO(""))
    with pytest.raises(ValueError):
        assert ghpypi.get_github_token(None, True)

    # token provided on stdin but it is white space
    mocker.patch("sys.stdin", io.StringIO("       "))
    with pytest.raises(ValueError):
        assert ghpypi.get_github_token(None, True)

    # token in the environment
    mocker.patch("os.environ.get", lambda key: "foobarbaz" if key == "GITHUB_TOKEN" else original_environ(key))
    assert ghpypi.get_github_token(None, False) == "foobarbaz"

    # token in environment but empty
    mocker.patch("os.environ.get", lambda key: "" if key == "GITHUB_TOKEN" else original_environ(key))
    with pytest.raises(ValueError):
        ghpypi.get_github_token(None, False)

    # token in environment but empty spaces
    mocker.patch("os.environ.get", lambda key: "    " if key == "GITHUB_TOKEN" else original_environ(key))
    with pytest.raises(ValueError):
        ghpypi.get_github_token(None, False)


def test_get_releases(mocker: MockerFixture):
    # fake our access to github
    token = "abcdefghijklmnopqrstuvwxyz1234567890"  # noqa
    repository = ghpypi.Repository("paullockaby", "ghpypi")

    # test releases returning nothing ... here is what we're doing here:
    # our code needs to get a repository from a "github.Github" class which
    # is actually "github.MainClass.Github". So we're going to patch the
    # "get_repo" function on "github.MainClass.Github" class. we're going to
    # make it return a second mock that imitates a "github.Repository.Repository"
    # object implements the "get_releases" function and makes it return an
    # empty list. that is all.
    mock_get_repo = mocker.Mock(spec=github.Repository.Repository, **{
        "get_releases.return_value": [],
    })
    mocker.patch("github.MainClass.Github.get_repo", return_value=mock_get_repo)
    releases = list(ghpypi.get_releases(token, repository))
    assert len(releases) == 0

    # test releases returning something with no asset keyword.
    # much like the last example, except that when we call "get_releases" on
    # the "github.Repository.Repository" class, we need it to return another
    # mock that implements "github.GitRelease.GitRelease" and then we want to
    # mock the "raw_data" function and have it return an empty dict.
    mock_get_repo = mocker.Mock(spec=github.Repository.Repository, **{
        "get_releases.return_value": [
            mocker.Mock(spec=github.GitRelease.GitRelease, **{
                "raw_data": {},
            }),
        ],
    })
    mocker.patch("github.MainClass.Github.get_repo", return_value=mock_get_repo)
    releases = list(ghpypi.get_releases(token, repository))
    assert len(releases) == 0

    # test releases returning something with no assets.
    # this is exactly like the last example, except that we are putting things
    # into the dict that is being returned when "raw_data" is called.
    mock_get_repo = mocker.Mock(spec=github.Repository.Repository, **{
        "get_releases.return_value": [
            mocker.Mock(spec=github.GitRelease.GitRelease, **{
                "raw_data": {"assets": []},
            }),
        ],
    })
    mocker.patch("github.MainClass.Github.get_repo", return_value=mock_get_repo)
    releases = list(ghpypi.get_releases(token, repository))
    assert len(releases) == 0


def test_create_releases():
    pass

# to test:
#  - create_releases (need a list of github objects)
#  - create_package (needs a list of releases)
#  - build (needs a dict of Package Name as key and set of Packages as value, mock file system)
#  - get_package_json (needs a list of Packages)
