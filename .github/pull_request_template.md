## Summary

-

## Target branch

- [ ] Base branch is `develop` for normal feature/fix/docs/refactor work.
- [ ] Base branch is `main` only for release or hotfix PRs.

## Changes

-

## Validation

- [ ] `python -m compileall pkuclaw scripts`
- [ ] `python -m unittest discover`
- [ ] Docs build if docs changed: `cd docs-site && npm ci && npm run build`
- [ ] Not run / not applicable: <!-- explain -->

## Risk / rollback

-

## Checklist

- [ ] No secrets, tokens, cookies, local runtime data, or build artifacts are included.
- [ ] The PR is focused and does not mix unrelated changes.
- [ ] If this is a hotfix, the fix will also be synced back to `develop`.

