# ghpypi

A Python package index generator for releases on GitHub that uses GitHub Pages. This looks at the list of releases on one or more GitHub repositories and generates HTML out of it that can then be served up with GitHub Pages and used by pip to install your libraries.

![GitHub License](https://img.shields.io/github/license/paullockaby/ghpypi)
![GitHub Release](https://img.shields.io/github/v/release/paullockaby/ghpypi)
![Python Version from PEP 621 TOML](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fpaullockaby%2Fghpypi%2Fmain%2Fpyproject.toml)
[![Merge Pipelines](https://github.com/paullockaby/ghpypi/actions/workflows/merge.yaml/badge.svg)](https://github.com/paullockaby/ghpypi/actions/workflows/merge.yaml)

[![Mastodon Follow](https://img.shields.io/mastodon/follow/106882571030731815?domain=https%3A%2F%2Funcontrollablegas.com)](https://uncontrollablegas.com/@paul)

## Table of contents

* [Introduction](#introduction)
* [Quick start](#quick-start)
* [Development](#development)
* [Known issues and limitations](#known-issues-and-limitations)
* [Getting help](#getting-help)
* [Contributing](#contributing)
* [License](#license)
* [Acknowledgments](#acknowledgments)

## Introduction

This repository is a combination of two parts:

1. It is a PyPI repository for tools that created by this organization.
2. It is a project that can be used to generate your own PyPI repository using GitHub Pages.

How is this different from other static PyPI index generators? This one takes a list of GitHub repositories, uses the GitHub API to get a list of releases for those repositories, and then makes static pages that deploy well with GitHub Pages.

## Quick start

To get started we are going to:

1. Generate a GitHub token with the `repo` permissions.
1. Create a list of GitHub repositories that contain releases that we want to index into our new PyPI repository.
1. Run the initial static page generation.
1. Automate static page generation for new releases.

### Make a Copy of This Repository

To use this GitHub repository to create your own PyPI repository start by forking this GitHub repository into your own GitHub organization.

### Generate Deployment Key

You will want to generate an SSH deploy key for the repository, like this:

```
ssh-keygen -t ed25519 -C commitizen -f deploy_key -P ""
```

This will create two files: `deploy_key` and `deploy_key.pub`. **DO NOT COMMIT THESE.** Save them off somewhere for future reference.

Once you have the SSH keys, take the `deploy_key.pub` file and add it as a deploy key to the repo and make sure that it has write access. Take the private key, aka the non `.pub` file, and create a secret called `DEPLOY_KEY` in the repo. This will be used by ghpypi (and commitizen if you do not disable it) to push commits with changelog updates to the `main` branch during a release.

### Creating a List of GitHub Repositories

Next, create a file in the root of this GitHub repository. The file should be called `repositories.txt` and there is already an example. The file should contain the list of all the GitHub repositories that you want to poll for new releases to add to your PyPI repository. It might look like this:

    paullockaby/ghpypi

In the above example we have exactly one GitHub repository called `ghpypi` and it is under the `paullockaby` owner.

This tool uses Poetry run so you may need to install Poetry and then set up Poetry, like this:

    $ poetry install

Once the file has been created, invoke the script:

    $ echo $GITHUB_TOKEN | poetry run ghpypi --output docs --repositories repositories.txt --token-stdin

The newly built static index can now be found under `docs` and you can use [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site) to share the `docs` directory.

### Automatically Generating Static Files

You might want to put this whole thing into some sort of cron job to rebuild on a regular basis. We can use GitHub Actions to accomplish that. Create a GitHub Actions workflow in your GitHub repository. Call it `.github/workflows/generate-index.yaml` and make it look like this:

```yaml
name: Upload GitHub Pages

on:
  # allow triggering manually
  workflow_dispatch:

  # allow programmatic triggers
  repository_dispatch:

  # run every night at 12am, UTC
  schedule:
    - cron: "0 0 * * *"

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          ssh-key: "${{ secrets.DEPLOY_KEY }}"

      - name: Install poetry
        run: pipx install poetry

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12.x"
          cache: "poetry"

      - name: Setup GitHub Pages
        id: pages
        uses: actions/configure-pages@v5

      - name: Build site
        run: |
          poetry install --no-interaction
          poetry run ghpypi --output=docs --repositories=repositories.txt --token=${{ secrets.GITHUB_TOKEN }}

      - name: Push pages updates
        run: |
          git commit -am "chore: automatic index update [skip ci]"
          git push origin main

      - name: Upload site
        uses: actions/upload-pages-artifact@v3
        with:
          path: ./docs

  deploy:
    runs-on: ubuntu-latest

    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}

    needs: [build]

    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

If you want to trigger a rebuild of the PyPI repository index when another GitHub repository does something, like when one of your repositories generates a new release, then you can do that with a GitHub Action as well. Add this GitHub Action to your other GitHub repository to automatically trigger a build in this GitHub repository:

```yaml
  - name: update pypi
    uses: octokit/request-action@v2.x
    with:
      # leave this exactly as it is -- the values get replaced automatically
      route: POST /repos/{owner}/{repo}/actions/workflows/{workflow}/dispatches

      # change this to be the name of the organization where your GitHub Pages PyPI repository exists
      owner: myorg

      # change this to be the name of the GitHub repository referenced above
      repo: ghpypi

      # change this to be the name of the workflow in the GitHub repository that you're targeting
      workflow: generate-index.yaml

      # change this to be the name of the branch in the GitHub repository that you're targeting
      ref: main
    env:
      GITHUB_TOKEN: ${{ secrets.WORKFLOW_TOKEN }}
```

The `WORKFLOW_TOKEN` is a personal access token that is granted `repo` rights to GitHub repositories in your organization. You cannot use the regular `GITHUB_TOKEN` secret provided by the GitHub Actions runner because GitHub does not want you to inadvertently create circular actions. (You can _purposely_ create circular actions, though!)

### Using your deployed index server with pip (or poetry)

When running pip, pass `--extra-index-url https://myorg.github.io/ghpypi/simple` or set the environment variable `PIP_EXTRA_INDEX_URL==https://myorg.github.io/ghpypi/simple`. If you're using [poetry](https://python-poetry.org/) then simply add this to your `pyproject.toml` file:

```toml
[[tool.poetry.source]]
name = "ghpypi"
url = "https://myorg.github.io/ghpypi/simple/"
```

## Development

In order to do development on this repository you must have [poetry](https://python-poetry.org/) and [pre-commit](https://pre-commit.com/) installed. For example, if you have Homebrew installed you can run this command:

```commandline
brew install poetry pre-commit
```

After installing these, clone this project and run this commands:

```commandline
make install
```

Running that will install the pre-commit hook and set up your poetry environment. Now you can begin development. Some common development commands:

```commandline
make test  # run all tests, perform static typing checks, and generate a coverage report
make pre-commit  # run pre-commit hooks (i.e. black, isort, and flake8) before committing
```

## Known issues and limitations

There are no known issues or limitations at this time.

## Getting help

Please use GitHub Issues to raise bugs or feature requests or to otherwise communicate with the project. For more details on how to get help, please read the [contributing](#contributing) section.

## Contributing

This project welcomes contributions! Please be cognizant of the [code of conduct](CODE_OF_CONDUCT.md) when interacting with or contributing to this project. You may contribute in many ways:

* By filing bug reports. Please use GitHub Issues to submit any bugs that you may encounter.
* By filing feature requests. Be aware that we may not implement every feature request but we will evaluate them and provide feedback.
* By submitting pull requests. Please use GitHub to submit pull requests.
* By writing documentation. If you see something that could be explained better or is not explained at all, please submit a pull request to update the documentation. Alternatively, just submit an issue describing what is unclear and how it could be more clear and we will endeavor to update the documentation.

If you choose to submit a pull request please follow these guidelines:

* Please provide a clean, concise title for your pull request and a clear description of what you are changing so that it may be evaluated more effectively.
* Limit any pull request to a single change or the minimum number of changes necessary to achieve the feature or bug fix. Many smaller pull requests are preferred over fewer, larger pull requests.
* No pull request will be reviewed unless and until the linter and the tests pass. You can the linter and the tests locally and we encourage you to do so.
* Not every change can or may be accepted. If you are uncertain whether your pull request would be accepted then please open an issue before beginning work to discuss what you would like to do.
* This project is licensed using the Apache License and that by submitting code you accept that your code will be licensed the same.

Again, please use GitHub Issues and GitHub Pull Requests to communicate with the project. It is the fastest and most effective way to be heard.

If you have security feedback you can reach out to [contact@paullockaby.com](mailto:contact@paullockaby.com) to raise your security finding in a confidential manner so that we may provide a fix when the vulnerability is made public. If you are not sure that your feedback is security related please err on the side of caution and send the email. The worst that will happen is you will be asked to create a GitHub Issue.

## License

Copyright &copy; 2024 Paul Lockaby. All rights reserved.

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain a copy of the License at [http://www.apache.org/licenses/LICENSE-2.0](http://www.apache.org/licenses/LICENSE-2.0)

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.

## Acknowledgements

This package is based heavily on [dumb-pypi](https://github.com/chriskuehl/dumb-pypi) which was created by and is maintained by [Chris Kuehl](https://github.com/chriskuehl).
