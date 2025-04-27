import collections
import hashlib
import importlib.metadata
import json
import logging
import os.path
import re
import sys
from datetime import datetime
from typing import Any, Iterator, NamedTuple, Optional, cast

import distlib.wheel  # type: ignore
import github
import jinja2
import packaging.utils
import packaging.version
import requests
from atomicwrites import atomic_write

logger = logging.getLogger(__name__)


def get_version(package_name: str = __name__) -> str:
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"


def remove_package_extension(name: str) -> str:
    name, ext = os.path.splitext(name)
    if not ext:
        raise ValueError(f"invalid package name: {name}")
    if name.endswith(".tar"):
        name, _ = os.path.splitext(name)

    return name


def guess_name_version_from_filename(filename: str) -> tuple[str, Optional[str]]:
    if filename.endswith(".whl"):
        m = distlib.wheel.FILENAME_RE.match(filename)
        if m is not None:
            return m.group("nm"), m.group("vn")

        # found nothing in our regex, bail
        raise ValueError(f"invalid package name: {filename}")

    # These don't have a well-defined format like wheels do, so they are sort
    # of "best effort", with lots of tests to back them up. The most important
    # thing is to correctly parse the name.
    name = remove_package_extension(filename)
    version = None

    if "-" in name:
        if name.count("-") == 1:
            name, version = name.split("-")
        else:
            parts = name.split("-")
            for i in range(len(parts) - 1, 0, -1):
                part = parts[i]
                if "." in part and re.search(r"\d", part):
                    name, version = "-".join(parts[0:i]), "-".join(parts[i:])

    # possible with poorly named files
    if len(name) <= 0:
        raise ValueError(f"invalid package name: {filename}")

    return name, version


class Repository(NamedTuple):
    owner: str
    name: str


class Artifact(NamedTuple):
    filename: str
    url: str
    sha256: str
    uploaded_at: datetime
    uploaded_by: str


class Package(NamedTuple):
    filename: str
    url: str
    sha256: str
    uploaded_at: datetime
    uploaded_by: str

    # the above fields all come from the artifact
    # these fields get calculated by whatever creates us
    name: str
    version: packaging.version.Version

    def __str__(self: "Package") -> str:
        return f"{self.version}, {self.uploaded_at.strftime('%Y-%m-%d %H:%M:%S')}, {self.uploaded_by}"  # noqa Q000

    def __lt__(self: tuple[object, ...], other: tuple[object, ...]) -> bool:
        return cast("Package", self).sort_key < cast("Package", other).sort_key

    @property
    def sort_key(
        self: "Package",
    ) -> tuple[str, packaging.version.Version, str]:
        """Sort key for a file name."""
        return (
            self.name,
            self.version,
            # This looks ridiculous, but it's so that like extensions sort
            # together when the name and version are the same (otherwise it
            # depends on how the file name is normalized, which means sometimes
            # wheels sort before tarballs, but not always).
            # Alternatively we could just grab the extension, but that's less
            # amusing, even though it took 6 lines of comments to explain this.
            self.filename[::-1],
        )


def get_package_json(files: list[Package]) -> dict[str, Any]:
    # https://warehouse.pypa.io/api-reference/json.html
    # note: the full api contains much more, we only output the info we have
    by_version: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)

    latest = files[-1]
    for f in files:
        by_version[str(f.version)].append(
            {
                "filename": f.filename,
                "url": f.url,
                "digests": {"sha256": f.sha256},
            },
        )

    return {
        "info": {
            "name": latest.name,
            "version": str(latest.version),
        },
        "releases": by_version,
        "urls": by_version[str(latest.version)],
    }


def build(packages: dict[str, set[Package]], output: str, title: str) -> None:
    simple = os.path.join(output, "simple")
    pypi = os.path.join(output, "pypi")

    jinja_env = jinja2.Environment(
        loader=jinja2.PackageLoader("ghpypi", "templates"),
        autoescape=True,
    )
    jinja_env.globals["title"] = title

    # sorting package versions is actually pretty expensive, so we do it once at the start
    sorted_packages = {name: sorted(files) for name, files in packages.items()}

    for package_name, sorted_files in sorted_packages.items():
        logger.info("processing %s with %d files", package_name, len(sorted_files))

        # /simple/{package}/index.html
        simple_package_dir = os.path.join(simple, package_name)
        os.makedirs(simple_package_dir, exist_ok=True)
        with atomic_write(
            os.path.join(simple_package_dir, "index.html"),
            overwrite=True,
        ) as f:
            f.write(
                jinja_env.get_template("package.html").render(
                    package_name=package_name,
                    files=sorted_files,
                ),
            )

        # /pypi/{package}/json
        pypi_package_dir = os.path.join(pypi, package_name)
        os.makedirs(pypi_package_dir, exist_ok=True)
        with atomic_write(os.path.join(pypi_package_dir, "json"), overwrite=True) as f:
            json.dump(get_package_json(sorted_files), f)

    # /simple/index.html
    os.makedirs(simple, exist_ok=True)
    with atomic_write(os.path.join(simple, "index.html"), overwrite=True) as f:
        f.write(
            jinja_env.get_template("simple.html").render(
                package_names=sorted_packages,
            ),
        )

    # /index.html
    with atomic_write(os.path.join(output, "index.html"), overwrite=True) as f:
        f.write(
            jinja_env.get_template("index.html").render(
                packages=sorted(
                    (
                        package,
                        sorted_versions[-1].version,
                    )
                    for package, sorted_versions in sorted_packages.items()
                ),
            ),
        )


def create_package(artifact: Artifact) -> Package:
    if not re.match(r"[a-zA-Z\d_\-\.\+]+$", artifact.filename) or ".." in artifact.filename:
        raise ValueError(f"unsafe package name: {artifact.filename}")

    # set values that the user did not provide
    name, version = guess_name_version_from_filename(artifact.filename)
    name = packaging.utils.canonicalize_name(name)

    # parse the version to mutate it
    parsed_version = packaging.version.parse(version or "0")

    return Package(
        filename=artifact.filename,
        name=name,
        version=parsed_version,
        url=artifact.url,
        sha256=artifact.sha256,
        uploaded_at=artifact.uploaded_at,
        uploaded_by=artifact.uploaded_by,
    )


def create_packages(artifacts: Iterator[Artifact]) -> dict[str, set[Package]]:
    packages: dict[str, set[Package]] = collections.defaultdict(set)
    for artifact in artifacts:
        try:
            package = create_package(artifact)
        except ValueError as e:
            logger.warning("%s (skipping package)", e)
        else:
            packages[package.name].add(package)

    return packages


def load_repositories(path: str) -> Iterator[Repository]:
    with open(path, "rt", encoding="utf-8") as f:
        for line in f.read().splitlines():
            # strip and skip comments
            line = line.strip()
            if line.startswith("#") or len(line) == 0:
                continue

            # expect each line to look like "owner/repo"
            parts = line.split("/")
            if len(parts) == 2 and len(parts[0]) and len(parts[1]):
                logger.info("found repository: %s", line)
                yield Repository(owner=parts[0], name=parts[1])
            else:
                raise ValueError(f"invalid repository name: {line}")


def get_github_token(token: Optional[str], token_stdin: bool) -> str:
    # if provided then use it
    if token is not None:
        token = token.strip()
        if len(token):
            return token

    # if we were told to look to stdin then look there
    if token_stdin:
        tokens = sys.stdin.read().splitlines()
        if len(tokens) and len(tokens[0]):
            token = tokens[0].strip()
            if len(token):
                return token

    # if we didn't find it anywhere else then look for an environment variable
    token = os.environ.get("GITHUB_TOKEN")
    if token is not None:
        token = token.strip()
        if len(token):
            return token

    # no token found anywhere
    raise ValueError("No value for GITHUB_TOKEN.")


def get_artifacts(token: str, repository: Repository) -> Iterator[Artifact]:
    logger.info(
        "fetching release artifacts for %s/%s",
        repository.owner,
        repository.name,
    )

    gh = github.Github(token)
    gh_repo = gh.get_repo(f"{repository.owner}/{repository.name}")
    releases = gh_repo.get_releases()

    for release in releases:
        assets = release.raw_data.get("assets") or []
        yield from create_artifacts(assets)


def create_artifacts(assets: list[dict]) -> Iterator[Artifact]:
    if len(assets) == 0:
        return

    # keep track of all the assets that we've found
    results = []

    # keep track of any sha256 sums that we find
    sha256sums = {}

    for asset in assets:
        name = asset["name"]
        url = asset["browser_download_url"]

        # we only want wheels and tar.gz and maybe pre-existing checksums
        if not (name.endswith(".whl") or name.endswith(".gz") or name.endswith(".bz2") or name == "sha256sum.txt"):
            continue

        if name == "sha256sum.txt":
            response = requests.get(url, timeout=10)
            response.raise_for_status()  # we only expect 200 responses

            # set the encoding to ascii so that we don't make the system guess
            response.encoding = "ascii"

            # split the lines, then split each line
            sha256sums = {
                x[1]: x[0] for x in [line.strip().split() for line in response.text.split("\n") if len(line.strip())]
            }

        else:
            results.append(
                {
                    "filename": name,
                    "url": url,
                    "sha256": None,
                    "uploaded_at": datetime.fromisoformat(
                        asset["updated_at"].rstrip("Z"),
                    ),
                    "uploaded_by": asset["uploader"]["login"],
                },
            )

    for result in results:
        if result["filename"] in sha256sums:
            # found the hash, just add it to the file
            if result["filename"] in sha256sums:
                result["sha256"] = sha256sums[result["filename"]]
        else:
            # for any file that doesn't have a sha256 hash, download the file and calculate it
            response = requests.get(result["url"], stream=True, timeout=30)
            response.raise_for_status()  # we only expect 200 responses

            # expecting a binary response
            hasher = hashlib.sha256()
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:  # filter out keep-alive new chunks
                    hasher.update(chunk)

            result["sha256"] = hasher.hexdigest()

        yield Artifact(**result)


def run(
    repositories: str,
    output: str,
    token: str,
    token_stdin: bool,
    title: Optional[str] = None,
) -> None:
    packages = {}
    token = get_github_token(token, token_stdin)
    for repository in load_repositories(repositories):
        packages.update(create_packages(get_artifacts(token, repository)))

    # set a default title
    if title is None:
        title = "My Private PyPI"

    # this actually spits out HTML files
    build(packages, output, title)
