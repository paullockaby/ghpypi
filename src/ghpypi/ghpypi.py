import collections
import dataclasses
import json
import logging
import os.path
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple, Union

import distlib.wheel  # type: ignore
import jinja2
import packaging.utils
import packaging.version
import requests
from atomicwrites import atomic_write
from github import Github

logger = logging.getLogger(__name__)


def remove_extension(name: str) -> str:
    if name.endswith(("gz", "bz2")):
        name, _ = name.rsplit(".", 1)
    name, _ = name.rsplit(".", 1)
    return name


def guess_name_version_from_filename(filename: str) -> Tuple[str, Optional[str]]:
    if filename.endswith(".whl"):
        m = distlib.wheel.FILENAME_RE.match(filename)
        if m is not None:
            return m.group("nm"), m.group("vn")

        # found nothing in our regex, bail
        raise ValueError(f"invalid package name: {filename}")

    # These don't have a well-defined format like wheels do, so they are sort
    # of "best effort", with lots of tests to back them up. The most important
    # thing is to correctly parse the name.
    name = remove_extension(filename)
    version = None

    if "-" in name:
        if name.count("-") == 1:
            name, version = name.split("-")
        else:
            parts = name.split("-")
            for i in range(len(parts) - 1, 0, -1):
                part = parts[i]
                if "." in part and re.search(r"[0-9]", part):
                    name, version = "-".join(parts[0:i]), "-".join(parts[i:])

    # possible with poorly-named files
    if len(name) <= 0:
        raise ValueError(f"invalid package name: {filename}")

    return name, version


@dataclass(frozen=True)
class Repository:
    owner: str
    name: str


@dataclass(frozen=True)
class Release:
    filename: str
    url: str
    sha256: str
    uploaded_at: datetime
    uploaded_by: str


@dataclass(frozen=True, order=False)
class Package:
    filename: str
    url: str
    sha256: str
    uploaded_at: datetime
    uploaded_by: str
    name: str
    version: Union[packaging.version.LegacyVersion, packaging.version.Version]

    def __lt__(self: "Package", other: "Package") -> bool:
        return self.sort_key < other.sort_key

    def __gt__(self: "Package", other: "Package") -> bool:
        return self.sort_key > other.sort_key

    def __str__(self: "Package") -> str:
        info = str(self.version)
        if self.uploaded_at is not None:
            info += f", {self.uploaded_at.strftime('%Y-%m-%d %H:%M:%S')}"
        if self.uploaded_by is not None:
            info += f", {self.uploaded_by}"
        return info

    @property
    def sort_key(self: "Package") -> Tuple[str, Union[packaging.version.LegacyVersion, packaging.version.Version], str]:
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

    def __post_init__(self: "Package") -> None:
        # make sure that this thing is a valid file name
        if not re.match(r"[a-zA-Z0-9_\-\.\+]+$", self.filename) or ".." in self.filename:
            raise ValueError(f"unsafe package name: {self.filename}")


def get_package_json(files: List[Package]) -> Dict[str, Any]:
    # https://warehouse.pypa.io/api-reference/json.html
    # note: the full api contains much more, we only output the info we have
    by_version: Dict[str, List[Dict[str, Any]]] = collections.defaultdict(list)

    latest = files[-1]
    for f in files:
        by_version[str(f.version)].append({
            "filename": f.filename,
            "url": f.url,
            "digests": {"sha256": f.sha256},
        })

    return {
        "info": {
            "name": latest.name,
            "version": str(latest.version),
        },
        "releases": by_version,
        "urls": by_version[str(latest.version)],
    }


def build(packages: Dict[str, Set[Package]], output: str, title: str) -> None:
    simple = os.path.join(output, "simple")
    pypi = os.path.join(output, "pypi")

    jinja_env = jinja2.Environment(
        loader=jinja2.PackageLoader("ghpypi", "templates"),
        autoescape=True,
    )
    jinja_env.globals["title"] = title

    # Sorting package versions is actually pretty expensive, so we do it once
    # at the start.
    sorted_packages = {name: sorted(files) for name, files in packages.items()}

    for package_name, sorted_files in sorted_packages.items():
        logger.info("processing %s with %d files", package_name, len(sorted_files))

        # /simple/{package}/index.html
        simple_package_dir = os.path.join(simple, package_name)
        os.makedirs(simple_package_dir, exist_ok=True)
        with atomic_write(os.path.join(simple_package_dir, "index.html"), overwrite=True) as f:
            f.write(jinja_env.get_template("package.html").render(
                package_name=package_name,
                files=sorted_files,
            ))

        # /pypi/{package}/json
        pypi_package_dir = os.path.join(pypi, package_name)
        os.makedirs(pypi_package_dir, exist_ok=True)
        with atomic_write(os.path.join(pypi_package_dir, "json"), overwrite=True) as f:
            json.dump(get_package_json(sorted_files), f)

    # /simple/index.html
    os.makedirs(simple, exist_ok=True)
    with atomic_write(os.path.join(simple, "index.html"), overwrite=True) as f:
        f.write(jinja_env.get_template("simple.html").render(
            package_names=sorted(sorted_packages),
        ))

    # /index.html
    with atomic_write(os.path.join(output, "index.html"), overwrite=True) as f:
        f.write(jinja_env.get_template("index.html").render(
            packages=sorted(
                (
                    package,
                    sorted_versions[-1].version,
                )
                for package, sorted_versions in sorted_packages.items()
            ),
        ))


def create_packages(releases: Iterator[Release]) -> Dict[str, Set[Package]]:
    packages: Dict[str, Set[Package]] = collections.defaultdict(set)
    for release in releases:
        try:
            package_data = dataclasses.asdict(release)

            # set values that the user did not provide
            name, version = guess_name_version_from_filename(release.filename)
            package_data["name"] = packaging.utils.canonicalize_name(name)

            # parse the version to mutate it
            package_data["version"] = packaging.version.parse(version or "0")

            package = Package(**package_data)
        except ValueError as e:
            logger.warning("%s (skipping package)", e)
        else:
            packages[package.name].add(package)

    return packages


def load_repositories(path: str) -> Iterator[Repository]:
    with open(path, "rt", encoding="utf-8") as f:
        for line in f.read().splitlines():
            parts = line.split("/")
            if len(parts) == 2:
                logger.info("found repository: %s", line)
                yield Repository(owner=parts[0], name=parts[1])
            else:
                raise ValueError(f"invalid repository name: {line}")


def get_github_token(token: str, token_stdin: bool) -> str:
    # if provided then use it
    if token is not None:
        return token

    # if we were told to look to stdin then look there
    if token_stdin:
        tokens = sys.stdin.read().splitlines()
        if len(tokens) and len(tokens[0]):
            return tokens[0]

    # if we didn't find it anywhere else then look for an environment variable
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token

    # no token found anywhere
    raise ValueError("No value for GITHUB_TOKEN.")


def get_releases(token: str, repository: Repository) -> Iterator[Release]:
    logger.info("fetching releases for %s/%s", repository.owner, repository.name)

    g = Github(token)
    r = g.get_repo(f"{repository.owner}/{repository.name}")

    releases = r.get_releases()
    for release in releases:
        assets = release.raw_data.get("assets", [])
        if len(assets) == 0:
            continue

        # keep track of all of the assets that we've found
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
                response = requests.get(url)
                response.raise_for_status()  # we only expect 200 responses

                # set the encoding to ascii so that we don't make the system guess
                response.encoding = "ascii"

                # split lines then split each line
                sha256sums = {x[1]: x[0] for x in [line.strip().split() for line in response.text.split("\n") if len(line.strip())]}

            else:
                results.append({
                    "filename": name,
                    "url": url,
                    "sha256": None,
                    "uploaded_at": datetime.fromisoformat(asset["updated_at"].rstrip("Z")),
                    "uploaded_by": asset["uploader"]["login"],
                })

        # add the sha256 sums (if they exist)
        for result in results:
            if result["filename"] in sha256sums:
                result["sha256"] = sha256sums[result["filename"]]

            yield Release(**result)


def run(repositories: str, output: str, token: str, token_stdin: bool, title: Optional[str] = None) -> None:
    packages = {}
    token = get_github_token(token, token_stdin)
    for repository in load_repositories(repositories):
        packages.update(create_packages(get_releases(token, repository)))

    # set a default title
    if title is None:
        title = "My Personal PyPI"

    # this actually spits out HTML files
    build(packages, output, title)
