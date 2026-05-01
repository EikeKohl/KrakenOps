# Releasing the `krakenops` SDK to PyPI

This repo ships an automated release pipeline using **OIDC trusted publishing** — no API tokens stored anywhere. Pushing a tag matching `krakenops-v*` triggers `.github/workflows/release-krakenops.yml`, which builds the SDK and publishes it to TestPyPI (always) and PyPI (for stable tags).

The Python module name is `tentacle`; the PyPI distribution name is `krakenops` (Pillow-style — see [ADR 0004](adr/0004-pypi-distribution-name.md)).

---

## One-time setup (manual, ~10 minutes)

The pipeline can't run until trusted publishing is configured on **both** PyPI and TestPyPI, plus matching environments on GitHub. This is a one-time owner-account action.

### 1. PyPI — add a pending publisher

1. Sign in at <https://pypi.org>.
2. Go to **Your account → Publishing → Add a new pending publisher**.
3. Fill in:

   | Field | Value |
   |---|---|
   | PyPI Project Name | `krakenops` |
   | Owner | `EikeKohl` |
   | Repository name | `KrakenOps` |
   | Workflow name | `release-krakenops.yml` |
   | Environment name | `pypi` |

4. Click **Add**.

### 2. TestPyPI — same thing, separately

1. Sign in at <https://test.pypi.org> (separate account from real PyPI).
2. **Your account → Publishing → Add a new pending publisher**.
3. Same fields as above except **Environment name** = `testpypi`.

### 3. GitHub — create the matching environments

1. <https://github.com/EikeKohl/KrakenOps/settings/environments>
2. Click **New environment**, name it `pypi`. Save.
3. Click **New environment**, name it `testpypi`. Save.

(Optional but recommended for `pypi`: under **Deployment protection rules**, enable **Required reviewers** → add yourself. That gives you a manual gate before the publish-to-real-PyPI step runs.)

That's the whole setup. From here it's all automated.

---

## Cutting a release

```sh
# 1. On main, bump the version. Update BOTH files:
sed -i '' 's/^version = "1.0.0"/version = "1.0.1"/' packages/tentacle/pyproject.toml
sed -i '' 's/^__version__ = "1.0.0"/__version__ = "1.0.1"/' packages/tentacle/src/tentacle/_version.py

# 2. Update the changelog.
$EDITOR packages/tentacle/CHANGELOG.md

# 3. Commit + push.
git add packages/tentacle/
git commit -m "sdk: release 1.0.1"
git push origin main

# 4. Tag and push the tag.
git tag -a krakenops-v1.0.1 -m "krakenops 1.0.1"
git push origin krakenops-v1.0.1
```

Pushing the tag triggers the release workflow:

1. **Build** — produces `dist/krakenops-1.0.1-py3-none-any.whl` + `.tar.gz`. Verifies the tag version matches `pyproject.toml`.
2. **TestPyPI** — publishes to <https://test.pypi.org/project/krakenops/>. Always runs.
3. **PyPI** — publishes to <https://pypi.org/project/krakenops/>. Only runs for stable tags (skipped if the tag contains `rc`, `a`, `b`, `.dev`, or `.post`).

Watch the run at <https://github.com/EikeKohl/KrakenOps/actions>.

## Pre-releases

```sh
git tag -a krakenops-v1.1.0rc1 -m "krakenops 1.1.0rc1"
git push origin krakenops-v1.1.0rc1
```

Builds + publishes to **TestPyPI only**. Real PyPI is skipped via the `if:` guard in the workflow.

## Verifying a release

```sh
# After TestPyPI:
pip install -i https://test.pypi.org/simple/ krakenops==1.0.1
python -c "import tentacle; print(tentacle.__version__)"

# After PyPI:
pip install krakenops==1.0.1
python -c "import tentacle; print(tentacle.__version__)"
```

(Note the install uses `krakenops`, the import uses `tentacle`. See ADR 0004.)

## Troubleshooting

- **"Trusted publisher not configured"** — the pending publisher on PyPI/TestPyPI isn't set up yet, or the workflow filename / environment name doesn't match. Re-check step 1 / 2 above.
- **`tag version (X) and pyproject.toml version (Y) disagree`** — the build job's pre-flight caught a mismatch. Fix the version in `pyproject.toml` + `_version.py`, push, and re-tag.
- **"first publish only"** — PyPI's pending-publisher mechanism converts to a regular trusted publisher after the first successful release. After that, only the workflow filename + env name + repo identity need to match; the project already exists.

## Docker images (GHCR)

Pushing a `krakenops-v*` tag *also* triggers `.github/workflows/release-docker.yml`, which builds the backend and dashboard images and pushes multi-arch (linux/amd64 + linux/arm64) to GHCR:

- `ghcr.io/eikekohl/krakenops-backend:0.0.1` and `:latest`
- `ghcr.io/eikekohl/krakenops-dashboard:0.0.1` and `:latest`

(GitHub lowercases the owner namespace automatically.)

**First-time setup:** new GHCR packages default to **private**. After the first successful run, flip each package to public so users can `docker pull` without authenticating. Each package has a dedicated settings page:

```
https://github.com/users/EikeKohl/packages/container/krakenops-backend/settings
https://github.com/users/EikeKohl/packages/container/krakenops-dashboard/settings
```

Scroll to the **Danger Zone** and click **Change visibility** → **Public**. Once flipped, future pushes to the same package stay public.

The workflow also accepts `workflow_dispatch` for manual rebuilds without pushing a new tag (useful if a Dockerfile-only fix is needed mid-version).

## Future work

- **Backend / dashboard versioning in PyPI-style.** The backend isn't published anywhere today; if/when we want a `krakenops-backend` PyPI distribution, this workflow's structure replicates cleanly.
