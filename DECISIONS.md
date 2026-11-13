# Decisions

## Repository settings (2026-11-13)

The repository is public. These GitHub settings were chosen for it:

- Secret scanning with push protection is on, so a pushed secret is blocked.
- Dependabot alerts are on. Dependabot security update pull requests are off: alerts are enough for a finished project.
- CodeQL default setup is on.
- Private vulnerability reporting is on; [SECURITY.md](SECURITY.md) states the policy.
- The ruleset "Protect main history" applies to the default branch and blocks force pushes and deletion. It requires no pull request and no status check, because the project is finished and later small changes may go directly to `main`; CI still runs on every push to `main` and on every pull request.
- The Projects tab is off.
- Merged branches are deleted automatically.
