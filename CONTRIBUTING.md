# Contributing to Luma Studio

Use a fresh data directory when developing against an existing studio installation:

```sh
AUTEUR_DATA=./data/dev PORT=7821 python3 studio.py
```

Run both suites before submitting a pull request:

```sh
python3 -m unittest discover -s tests -v
node --test tests/*.test.js
```

Describe the behavior before and after the change. For workflow or media changes, include the input shape and how you verified the output. Use synthetic examples in issues and pull requests. Keep `.env`, production databases, private scripts and media out of commits.

When changing workflow templates, update the corresponding generator in `workflows/` and commit the regenerated output. Keep provider credentials in the local environment.
