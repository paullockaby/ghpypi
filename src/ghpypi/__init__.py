import argparse
import logging
import sys
from typing import List

from ghpypi.ghpypi import get_version, run

# calculate what version of this program we are running
__version__ = get_version()


def parse_arguments(arguments: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ghpypi")

    token_input_group = parser.add_mutually_exclusive_group(required=False)
    token_input_group.add_argument(
        "--token",
        metavar="TOKEN",
        dest="token",
        help="your GitHub token",
    )
    token_input_group.add_argument(
        "--token-stdin",
        action="store_true",
        help="your GitHub token from stdin",
    )

    parser.add_argument(
        "--repositories",
        metavar="PATH",
        help="path to a list of repositories (one per line)",
        required=True,
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="path to output to",
        required=True,
    )
    parser.add_argument(
        "--title",
        help="site title (for web interface)",
        default="My Private PyPI",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        dest="verbose",
        action="store_true",
        default=False,
        help="send verbose output to the console",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=__version__,
        help="return the version number and exit",
    )
    return parser.parse_args(arguments)


def main() -> None:
    args = parse_arguments(sys.argv[1:])

    logging.basicConfig(
        format="[%(asctime)s] %(levelname)-8s - %(message)s",
        level=logging.DEBUG if args.verbose else logging.INFO,
        stream=sys.stdout,
    )

    run(
        args.repositories,
        args.output,
        args.token,
        args.token_stdin,
        args.title,
    )


if __name__ == "__main__":
    main()
