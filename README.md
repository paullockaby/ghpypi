# ghpypi
A Python package index generator for GitHub using GitHub Pages. This looks at the list of releases on a GitHub repository and generates HTML out of it that can then be served up with GitHub Pages and used by pip to install your libraries.

## What is this?

This repository is a combination of two parts:

1. It is a PyPI repository for tools that created by this organization.
2. It is a project that can be used to generate your own PyPI repository using GitHub Pages.

How is this different from other static pypI index generators? This one takes a list of GitHub repositories, uses the GitHub API to get a list of releases for those repositories, and then makes static pages that deploy well with GitHub Pages.

## Getting Started

To get started we are going to:

1. Create a list of GitHub repositories that contain releases that we want to index into our new PyPI repository.
2. Run the initial static page generation.
3. Automate static page generation for new releases.

### Make a Copy of This Repository

To use this GitHub repository to create your own PyPI repository start by forking this GitHub repository into your own GitHub organization.

### Creating a List of GitHub Repositories

Next, create a file in the root of this GitHub repository. The file should be called `repositories.txt` and there is already an example. The file should contain the list of all the GitHub repositories that you want to poll for new releases to add to your PyPI repository. It might look like this:

    paullockaby/ghpypi

In the above example we have exactly one GitHub repository called `ghpypi` and it is under the `paullockaby` owner.

Once the file has been created, invoke the script:

    $ echo $GITHUB_TOKEN | ghpypi --output docs --repositories repositories --token-stdin

The newly built static index can now be found under `docs` and you can use [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site) to share the `docs` directory.

### Automatically Generating Static Files

You might want to put this whole thing into some sort of cron job to rebuild on a regular basis. We can use GitHub Actions to accomplish that. Create a GitHub Actions workflow in your GitHub repository. Call it `.github/workflows/generate-index.yaml` and make it look like this:

```yaml
name: Generate Index

on:
  # allow manual triggers
  workflow_dispatch:

  # allow programmatic triggers
  repository_dispatch:

  # run every night at midnight UTC
  schedule:
    - cron: "0 0 * * *"

jobs:
  generate:
    runs-on: ubuntu-latest

    steps:
      - name: checkout
        uses: actions/checkout@v3

      - name: setup python
        uses: actions/setup-python@v2
        with:
          python-version: 3.10

      - name: generate index
        run: |
          pip install poetry
          poetry install --no-ansi --no-interaction --no-dev
          poetry run ghpypi --output=docs --repositories=repositories.txt --token=${{ secrets.GITHUB_TOKEN }}

      - uses: stefanzweifel/git-auto-commit-action@v4
        with:
          commit_message: automatic index update [skip ci]
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

The `WORKFLOW_TOKEN` is a personal access token that is granted admin rights to GitHub repositories in your organization. You cannot use the regular `GITHUB_TOKEN` secret provided by the GitHub Actions runner because GitHub does not want you to inadvertently create circular actions. (You can _purposely_ create circular actions, though!)

### Using your deployed index server with pip (or poetry)

When running pip, pass `--extra-index-url https://myorg.github.io/ghpypi/simple` or set the environment variable `PIP_EXTRA_INDEX_URL==https://myorg.github.io/ghpypi/simple`. If you're using [poetry](https://python-poetry.org/) then simply add this to your `pyproject.toml` file:

```toml
[[tool.poetry.source]]
name = "ghpypi"
url = "https://myorg.github.io/ghpypi/simple/"
```

## TODO

This project needs some tests.

## Credits

This package is based heavily on [dumb-pypi](https://github.com/chriskuehl/dumb-pypi) which was created by and is maintained by [Chris Kuehl](https://github.com/chriskuehl).
