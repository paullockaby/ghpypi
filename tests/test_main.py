import hashlib
import io
import os
from datetime import datetime
from pathlib import PosixPath

import github
import packaging.version
import pytest
import responses
from pytest_mock import MockerFixture

from ghpypi import ghpypi
from ghpypi.ghpypi import Artifact, Package


@pytest.mark.parametrize(
    ("package_name", "version"),
    (
        ("completely invalid package", "0.0.0"),
        ("ghpypi", "0.0.0"),
        ("pytest", pytest.__version__),
    ),
)
def test_get_version(package_name: str, version: str):
    assert ghpypi.get_version(package_name) == version


@pytest.mark.parametrize(
    ("file_name", "cleaned"),
    (
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
    ),
)
def test_remove_extension(file_name: str, cleaned: str):
    assert ghpypi.remove_package_extension(file_name) == cleaned


@pytest.mark.parametrize(
    ("file_name", "name", "version"),
    (
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
        (
            "package-123-1.3.7+build.11.e0f985a.zip",
            "package-123",
            "1.3.7+build.11.e0f985a",
        ),
    ),
)
def test_guess_name_version_from_filename(file_name: str, name: str, version: str):
    assert ghpypi.guess_name_version_from_filename(file_name) == (name, version)


@pytest.mark.parametrize(
    ("file_name", "name", "version"),
    (
        ("dumb-init-0.1.0.linux-x86_64.tar.gz", "dumb-init", "0.1.0"),
        ("greenlet-0.3.4-py3.1-win-amd64.egg", "greenlet", "0.3.4"),
        ("numpy-1.7.0.win32-py3.1.exe", "numpy", "1.7.0"),
        ("surf.sesame2-0.2.1_r291-py2.5.egg", "surf.sesame2", "0.2.1_r291"),
    ),
)
def test_guess_name_version_from_filename_only_name(
    file_name: str, name: str, version: str
):
    """Broken version check tests.
    The real important thing is to be able to parse the name, but it's nice if
    we can parse the versions too. Unfortunately, we can't yet for these cases.
    """
    parsed_name, parsed_version = ghpypi.guess_name_version_from_filename(file_name)
    assert parsed_name == name

    # If you can make this assertion fail, great! Move it up above!
    assert parsed_version != version


@pytest.mark.parametrize(
    "file_name",
    (
        "",
        "lol",
        "lol-sup",
        "-20160920.193125.zip",
        "playlyfe-0.1.1-2.7.6-none-any.whl",  # 2.7.6 is not a valid python tag
    ),
)
def test_guess_name_version_from_filename_invalid(file_name: str):
    with pytest.raises(ValueError):
        ghpypi.guess_name_version_from_filename(file_name)


def test_load_repositories(tmp_path: PosixPath):
    tmp_data = tmp_path / "repos.txt"
    tmp_data.write_text(
        """

        # this is a comment
        foo/bar
        baz/bat
    """
    )

    tmp_data_path = str(tmp_data)
    repos = ghpypi.load_repositories(tmp_data_path)
    result = list(repos)
    assert len(result) == 2
    assert result[0] == ghpypi.Repository("foo", "bar")
    assert result[1] == ghpypi.Repository("baz", "bat")


@pytest.mark.parametrize(
    "data",
    (
        "some invalid data",
        "; this is invalid",
        "foo/bar/asdf",
        "baz/",
        "bat",
        "/battery",
    ),
)
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
    mocker.patch(
        "os.environ.get",
        lambda key: None if key == "GITHUB_TOKEN" else original_environ(key),
    )

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
        ghpypi.get_github_token(None, True)

    # token provided on stdin but it is white space
    mocker.patch("sys.stdin", io.StringIO("       "))
    with pytest.raises(ValueError):
        ghpypi.get_github_token(None, True)

    # token in the environment
    mocker.patch(
        "os.environ.get",
        lambda key: "foobarbaz" if key == "GITHUB_TOKEN" else original_environ(key),
    )
    assert ghpypi.get_github_token(None, False) == "foobarbaz"

    # token in environment but empty
    mocker.patch(
        "os.environ.get",
        lambda key: "" if key == "GITHUB_TOKEN" else original_environ(key),
    )
    with pytest.raises(ValueError):
        ghpypi.get_github_token(None, False)

    # token in environment but empty spaces
    mocker.patch(
        "os.environ.get",
        lambda key: "    " if key == "GITHUB_TOKEN" else original_environ(key),
    )
    with pytest.raises(ValueError):
        ghpypi.get_github_token(None, False)


def test_get_artifacts(mocker: MockerFixture):
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
    mock_get_repo = mocker.Mock(
        spec=github.Repository.Repository,
        **{
            "get_releases.return_value": [],
        }
    )
    mocker.patch("github.MainClass.Github.get_repo", return_value=mock_get_repo)
    releases = list(ghpypi.get_artifacts(token, repository))
    assert len(releases) == 0

    # test releases returning something with no asset keyword.
    # much like the last example, except that when we call "get_releases" on
    # the "github.Repository.Repository" class, we need it to return another
    # mock that implements "github.GitRelease.GitRelease" and then we want to
    # mock the "raw_data" function and have it return an empty dict.
    mock_get_repo = mocker.Mock(
        spec=github.Repository.Repository,
        **{
            "get_releases.return_value": [
                mocker.Mock(
                    spec=github.GitRelease.GitRelease,
                    **{
                        "raw_data": {},
                    }
                ),
            ],
        }
    )
    mocker.patch("github.MainClass.Github.get_repo", return_value=mock_get_repo)
    releases = list(ghpypi.get_artifacts(token, repository))
    assert len(releases) == 0

    # test releases returning something with no assets.
    # this is exactly like the last example, except that we are putting things
    # into the dict that is being returned when "raw_data" is called.
    mock_get_repo = mocker.Mock(
        spec=github.Repository.Repository,
        **{
            "get_releases.return_value": [
                mocker.Mock(
                    spec=github.GitRelease.GitRelease,
                    **{
                        "raw_data": {"assets": []},
                    }
                ),
            ],
        }
    )
    mocker.patch("github.MainClass.Github.get_repo", return_value=mock_get_repo)
    releases = list(ghpypi.get_artifacts(token, repository))
    assert len(releases) == 0


def test_create_packages_empty():
    assert not ghpypi.create_packages([])


@pytest.mark.parametrize(
    ("artifacts", "packages"),
    (
        (
            [
                Artifact(
                    filename="ghpypi-1.0.1-py3-none-any.whl",
                    url="https://github.com/paullockaby/ghpypi/releases/download/v1.0.1/ghpypi-1.0.1-py3-none-any.whl",
                    sha256="ae36bbabd6424037f716c6a78f907d6f9b058ab399a042b2c8530087beca9c3c",
                    uploaded_at=datetime(2021, 12, 25, 6, 22, 19),
                    uploaded_by="github-actions[bot]",
                ),
                Artifact(
                    filename="ghpypi-1.0.1.tar.gz",
                    url="https://github.com/paullockaby/ghpypi/releases/download/v1.0.1/ghpypi-1.0.1.tar.gz",
                    sha256="0bca915a7d7129b4d5a21e5381fee0678016708139029c0c5ccadf71c0cf5265",
                    uploaded_at=datetime(2021, 12, 25, 6, 22, 19),
                    uploaded_by="github-actions[bot]",
                ),
                Artifact(
                    filename="ghpypi-1.0.0-py3-none-any.whl",
                    url="https://github.com/paullockaby/ghpypi/releases/download/v1.0.0/ghpypi-1.0.0-py3-none-any.whl",
                    sha256="8db833603bd5f71a7ae2d94364edcc996dd851f42da0069040cab954be53d48d",
                    uploaded_at=datetime(2021, 12, 25, 6, 16, 8),
                    uploaded_by="github-actions[bot]",
                ),
                Artifact(
                    filename="ghpypi-1.0.0.tar.gz",
                    url="https://github.com/paullockaby/ghpypi/releases/download/v1.0.0/ghpypi-1.0.0.tar.gz",
                    sha256="fa6dfbe92d7b150b788da980d53f07e6e84c4079118783d5905a72cc9b636ba3",
                    uploaded_at=datetime(2021, 12, 25, 6, 16, 9),
                    uploaded_by="github-actions[bot]",
                ),
                # these will be ignored because they're invalid
                Artifact(
                    filename="",
                    url="http://example.com/org/repo/releases/download/xxx/foobar.whl",
                    sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                    uploaded_at=datetime(2020, 1, 1, 0, 0, 0),
                    uploaded_by="github-actions[bot]",
                ),
                Artifact(
                    filename="lol",
                    url="http://example.com/org/repo/releases/download/xxx/foobar.whl",
                    sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                    uploaded_at=datetime(2020, 1, 1, 0, 0, 0),
                    uploaded_by="github-actions[bot]",
                ),
                Artifact(
                    filename="lol-sup",
                    url="http://example.com/org/repo/releases/download/xxx/foobar.whl",
                    sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                    uploaded_at=datetime(2020, 1, 1, 0, 0, 0),
                    uploaded_by="github-actions[bot]",
                ),
                Artifact(
                    filename="-20160920.193125.zip",
                    url="http://example.com/org/repo/releases/download/xxx/foobar.whl",
                    sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                    uploaded_at=datetime(2020, 1, 1, 0, 0, 0),
                    uploaded_by="github-actions[bot]",
                ),
                Artifact(
                    filename=".",
                    url="http://example.com/org/repo/releases/download/xxx/foobar.whl",
                    sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                    uploaded_at=datetime(2020, 1, 1, 0, 0, 0),
                    uploaded_by="github-actions[bot]",
                ),
                Artifact(
                    filename="..",
                    url="http://example.com/org/repo/releases/download/xxx/foobar.whl",
                    sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                    uploaded_at=datetime(2020, 1, 1, 0, 0, 0),
                    uploaded_by="github-actions[bot]",
                ),
                Artifact(
                    filename="/blah-2.tar.gz",
                    url="http://example.com/org/repo/releases/download/xxx/foobar.whl",
                    sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                    uploaded_at=datetime(2020, 1, 1, 0, 0, 0),
                    uploaded_by="github-actions[bot]",
                ),
                Artifact(
                    filename="lol-2.tar.gz/../",
                    url="http://example.com/org/repo/releases/download/xxx/foobar.whl",
                    sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                    uploaded_at=datetime(2020, 1, 1, 0, 0, 0),
                    uploaded_by="github-actions[bot]",
                ),
            ],
            {
                "ghpypi": {
                    Package(
                        filename="ghpypi-1.0.1-py3-none-any.whl",
                        url="https://github.com/paullockaby/ghpypi/releases/download/v1.0.1/ghpypi-1.0.1-py3-none-any.whl",
                        sha256="ae36bbabd6424037f716c6a78f907d6f9b058ab399a042b2c8530087beca9c3c",
                        uploaded_at=datetime(2021, 12, 25, 6, 22, 19),
                        uploaded_by="github-actions[bot]",
                        name="ghpypi",
                        version=packaging.version.Version("1.0.1"),
                    ),
                    Package(
                        filename="ghpypi-1.0.1.tar.gz",
                        url="https://github.com/paullockaby/ghpypi/releases/download/v1.0.1/ghpypi-1.0.1.tar.gz",
                        sha256="0bca915a7d7129b4d5a21e5381fee0678016708139029c0c5ccadf71c0cf5265",
                        uploaded_at=datetime(2021, 12, 25, 6, 22, 19),
                        uploaded_by="github-actions[bot]",
                        name="ghpypi",
                        version=packaging.version.Version("1.0.1"),
                    ),
                    Package(
                        filename="ghpypi-1.0.0-py3-none-any.whl",
                        url="https://github.com/paullockaby/ghpypi/releases/download/v1.0.0/ghpypi-1.0.0-py3-none-any.whl",
                        sha256="8db833603bd5f71a7ae2d94364edcc996dd851f42da0069040cab954be53d48d",
                        uploaded_at=datetime(2021, 12, 25, 6, 16, 8),
                        uploaded_by="github-actions[bot]",
                        name="ghpypi",
                        version=packaging.version.Version("1.0.0"),
                    ),
                    Package(
                        filename="ghpypi-1.0.0.tar.gz",
                        url="https://github.com/paullockaby/ghpypi/releases/download/v1.0.0/ghpypi-1.0.0.tar.gz",
                        sha256="fa6dfbe92d7b150b788da980d53f07e6e84c4079118783d5905a72cc9b636ba3",
                        uploaded_at=datetime(2021, 12, 25, 6, 16, 9),
                        uploaded_by="github-actions[bot]",
                        name="ghpypi",
                        version=packaging.version.Version("1.0.0"),
                    ),
                },
            },
        ),
    ),
)
def test_create_packages(artifacts, packages):
    assert ghpypi.create_packages(artifacts) == packages


@pytest.mark.parametrize(
    "artifact",
    (
        Artifact(
            filename="",
            url="http://example.com/org/repo/releases/download/xxx/foobar.whl",
            sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            uploaded_at=datetime(2020, 1, 1, 0, 0, 0),
            uploaded_by="github-actions[bot]",
        ),
        Artifact(
            filename="lol",
            url="http://example.com/org/repo/releases/download/xxx/foobar.whl",
            sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            uploaded_at=datetime(2020, 1, 1, 0, 0, 0),
            uploaded_by="github-actions[bot]",
        ),
        Artifact(
            filename="lol-sup",
            url="http://example.com/org/repo/releases/download/xxx/foobar.whl",
            sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            uploaded_at=datetime(2020, 1, 1, 0, 0, 0),
            uploaded_by="github-actions[bot]",
        ),
        Artifact(
            filename="-20160920.193125.zip",
            url="http://example.com/org/repo/releases/download/xxx/foobar.whl",
            sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            uploaded_at=datetime(2020, 1, 1, 0, 0, 0),
            uploaded_by="github-actions[bot]",
        ),
        Artifact(
            filename=".",
            url="http://example.com/org/repo/releases/download/xxx/foobar.whl",
            sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            uploaded_at=datetime(2020, 1, 1, 0, 0, 0),
            uploaded_by="github-actions[bot]",
        ),
        Artifact(
            filename="..",
            url="http://example.com/org/repo/releases/download/xxx/foobar.whl",
            sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            uploaded_at=datetime(2020, 1, 1, 0, 0, 0),
            uploaded_by="github-actions[bot]",
        ),
        Artifact(
            filename="/blah-2.tar.gz",
            url="http://example.com/org/repo/releases/download/xxx/foobar.whl",
            sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            uploaded_at=datetime(2020, 1, 1, 0, 0, 0),
            uploaded_by="github-actions[bot]",
        ),
        Artifact(
            filename="lol-2.tar.gz/../",
            url="http://example.com/org/repo/releases/download/xxx/foobar.whl",
            sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            uploaded_at=datetime(2020, 1, 1, 0, 0, 0),
            uploaded_by="github-actions[bot]",
        ),
    ),
)
def test_create_packages_invalid(artifact):
    with pytest.raises(ValueError):
        ghpypi.create_package(artifact)


def test_package_json():
    test_packages = sorted(
        [
            Package(
                filename="ghpypi-1.0.1-py3-none-any.whl",
                url="https://github.com/paullockaby/ghpypi/releases/download/v1.0.1/ghpypi-1.0.1-py3-none-any.whl",
                sha256="ae36bbabd6424037f716c6a78f907d6f9b058ab399a042b2c8530087beca9c3c",
                uploaded_at=datetime(2021, 12, 25, 6, 22, 19),
                uploaded_by="github-actions[bot]",
                name="ghpypi",
                version=packaging.version.Version("1.0.1"),
            ),
            Package(
                filename="ghpypi-1.0.0.tar.gz",
                url="https://github.com/paullockaby/ghpypi/releases/download/v1.0.0/ghpypi-1.0.0.tar.gz",
                sha256="fa6dfbe92d7b150b788da980d53f07e6e84c4079118783d5905a72cc9b636ba3",
                uploaded_at=datetime(2021, 12, 25, 6, 16, 9),
                uploaded_by="github-actions[bot]",
                name="ghpypi",
                version=packaging.version.Version("1.0.0"),
            ),
        ]
    )
    package_json = ghpypi.get_package_json(test_packages)
    assert package_json["info"] == {
        "name": "ghpypi",
        "version": "1.0.1",
    }
    assert package_json["urls"] == [
        {
            "digests": {
                "sha256": "ae36bbabd6424037f716c6a78f907d6f9b058ab399a042b2c8530087beca9c3c"
            },
            "filename": "ghpypi-1.0.1-py3-none-any.whl",
            "url": "https://github.com/paullockaby/ghpypi/releases/download/v1.0.1/ghpypi-1.0.1-py3-none-any.whl",
        },
    ]


def test_strings():
    test_packages = [
        Package(
            filename="ghpypi-1.0.1-py3-none-any.whl",
            url="https://github.com/paullockaby/ghpypi/releases/download/v1.0.1/ghpypi-1.0.1-py3-none-any.whl",
            sha256="ae36bbabd6424037f716c6a78f907d6f9b058ab399a042b2c8530087beca9c3c",
            uploaded_at=datetime(2021, 12, 25, 6, 22, 19),
            uploaded_by="github-actions[bot]",
            name="ghpypi",
            version=packaging.version.Version("1.0.1"),
        ),
        Package(
            filename="ghpypi-1.0.0.tar.gz",
            url="https://github.com/paullockaby/ghpypi/releases/download/v1.0.0/ghpypi-1.0.0.tar.gz",
            sha256="fa6dfbe92d7b150b788da980d53f07e6e84c4079118783d5905a72cc9b636ba3",
            uploaded_at=datetime(2021, 12, 25, 6, 16, 9),
            uploaded_by="github-actions[bot]",
            name="ghpypi",
            version=packaging.version.Version("1.0.0"),
        ),
    ]
    assert [str(x) for x in test_packages] == [
        "1.0.1, 2021-12-25 06:22:19, github-actions[bot]",
        "1.0.0, 2021-12-25 06:16:09, github-actions[bot]",
    ]


def test_sorting():
    test_packages = [
        ghpypi.create_package(
            ghpypi.Artifact(
                filename=filename,
                url="http://example.com/org/repo/releases/download/xxx/foobar.whl",
                sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                uploaded_at=datetime(2020, 1, 1, 0, 0, 0),
                uploaded_by="github-actions[bot]",
            )
        )
        for filename in (
            "fluffy-server-1.2.0.tar.gz",
            "fluffy_server-1.1.0-py2.py3-none-any.whl",
            "wsgi-mod-rpaf-2.0.0.tar.gz",
            "fluffy-server-10.0.0.tar.gz",
            "aspy.yaml-0.2.1.tar.gz",
            "wsgi-mod-rpaf-1.0.1.tar.gz",
            "aspy.yaml-0.2.1-py3-none-any.whl",
            "fluffy-server-1.0.0.tar.gz",
            "aspy.yaml-0.2.0-py2-none-any.whl",
            "fluffy_server-10.0.0-py2.py3-none-any.whl",
            "aspy.yaml-0.2.1-py2-none-any.whl",
            "fluffy-server-1.1.0.tar.gz",
            "fluffy_server-1.0.0-py2.py3-none-any.whl",
            "fluffy_server-1.2.0-py2.py3-none-any.whl",
        )
    ]
    sorted_names = [package.filename for package in sorted(test_packages)]
    assert sorted_names == [
        "aspy.yaml-0.2.0-py2-none-any.whl",
        "aspy.yaml-0.2.1-py2-none-any.whl",
        "aspy.yaml-0.2.1-py3-none-any.whl",
        "aspy.yaml-0.2.1.tar.gz",
        "fluffy_server-1.0.0-py2.py3-none-any.whl",
        "fluffy-server-1.0.0.tar.gz",
        "fluffy_server-1.1.0-py2.py3-none-any.whl",
        "fluffy-server-1.1.0.tar.gz",
        "fluffy_server-1.2.0-py2.py3-none-any.whl",
        "fluffy-server-1.2.0.tar.gz",
        "fluffy_server-10.0.0-py2.py3-none-any.whl",
        "fluffy-server-10.0.0.tar.gz",
        "wsgi-mod-rpaf-1.0.1.tar.gz",
        "wsgi-mod-rpaf-2.0.0.tar.gz",
    ]


@responses.activate
def test_create_artifacts_no_digest():
    assets = [
        {
            "name": "foobar-1.0.1.txt",
            "browser_download_url": "https://github.com/paullockaby/ghpypi/releases/download/v1.0.1/foobar-1.0.1.whl",
            "updated_at": "2021-12-25T06:22:19Z",
            "uploader": {"login": "github-actions[bot]"},
        },
        {
            "name": "ghpypi-1.0.1-py3-none-any.whl",
            "browser_download_url": "https://github.com/paullockaby/ghpypi/releases/download/v1.0.1/ghpypi-1.0.1-py3-none-any.whl",
            "updated_at": "2021-12-25T06:22:19Z",
            "uploader": {"login": "github-actions[bot]"},
        },
        {
            "name": "ghpypi-1.0.1.tar.gz",
            "browser_download_url": "https://github.com/paullockaby/ghpypi/releases/download/v1.0.1/ghpypi-1.0.1.tar.gz",
            "updated_at": "2021-12-25T06:22:19Z",
            "uploader": {"login": "github-actions[bot]"},
        },
    ]

    # this is what all of our responses will contain
    asset_data = b"this is an asset"
    asset_digest = hashlib.sha256(asset_data).hexdigest()

    for asset in assets:
        responses.get(
            asset["browser_download_url"],  # when we request this url
            asset_data,  # return this data
        )

    results = list(ghpypi.create_artifacts(assets))
    assert results == [
        ghpypi.Artifact(
            filename="ghpypi-1.0.1-py3-none-any.whl",
            url="https://github.com/paullockaby/ghpypi/releases/download/v1.0.1/ghpypi-1.0.1-py3-none-any.whl",
            sha256=asset_digest,
            uploaded_at=datetime(2021, 12, 25, 6, 22, 19),
            uploaded_by="github-actions[bot]",
        ),
        ghpypi.Artifact(
            filename="ghpypi-1.0.1.tar.gz",
            url="https://github.com/paullockaby/ghpypi/releases/download/v1.0.1/ghpypi-1.0.1.tar.gz",
            sha256=asset_digest,
            uploaded_at=datetime(2021, 12, 25, 6, 22, 19),
            uploaded_by="github-actions[bot]",
        ),
    ]


@responses.activate
def test_create_artifacts_digest():
    assets = [
        {
            "name": "sha256sum.txt",
            "browser_download_url": "https://github.com/paullockaby/ghpypi/releases/download/v1.0.1/sha256sum.txt",
            "updated_at": "2021-12-25T06:22:19Z",
            "uploader": {"login": "github-actions[bot]"},
        },
        {
            "name": "ghpypi-1.0.1-py3-none-any.whl",
            "browser_download_url": "https://github.com/paullockaby/ghpypi/releases/download/v1.0.1/ghpypi-1.0.1-py3-none-any.whl",
            "updated_at": "2021-12-25T06:22:19Z",
            "uploader": {"login": "github-actions[bot]"},
        },
        {
            "name": "ghpypi-1.0.1.tar.gz",
            "browser_download_url": "https://github.com/paullockaby/ghpypi/releases/download/v1.0.1/ghpypi-1.0.1.tar.gz",
            "updated_at": "2021-12-25T06:22:19Z",
            "uploader": {"login": "github-actions[bot]"},
        },
    ]

    # this is what all of our responses will contain
    asset_data = b"\n".join(
        [
            b"fa6dfbe92d7b150b788da980d53f07e6e84c4079118783d5905a72cc9b636ba3 ghpypi-1.0.1.tar.gz",
            b"ae36bbabd6424037f716c6a78f907d6f9b058ab399a042b2c8530087beca9c3c ghpypi-1.0.1-py3-none-any.whl",
        ]
    )
    responses.get(
        "https://github.com/paullockaby/ghpypi/releases/download/v1.0.1/sha256sum.txt",
        asset_data,
    )

    results = list(ghpypi.create_artifacts(assets))
    assert results == [
        ghpypi.Artifact(
            filename="ghpypi-1.0.1-py3-none-any.whl",
            url="https://github.com/paullockaby/ghpypi/releases/download/v1.0.1/ghpypi-1.0.1-py3-none-any.whl",
            sha256="ae36bbabd6424037f716c6a78f907d6f9b058ab399a042b2c8530087beca9c3c",
            uploaded_at=datetime(2021, 12, 25, 6, 22, 19),
            uploaded_by="github-actions[bot]",
        ),
        ghpypi.Artifact(
            filename="ghpypi-1.0.1.tar.gz",
            url="https://github.com/paullockaby/ghpypi/releases/download/v1.0.1/ghpypi-1.0.1.tar.gz",
            sha256="fa6dfbe92d7b150b788da980d53f07e6e84c4079118783d5905a72cc9b636ba3",
            uploaded_at=datetime(2021, 12, 25, 6, 22, 19),
            uploaded_by="github-actions[bot]",
        ),
    ]
