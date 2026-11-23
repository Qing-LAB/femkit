# Security

**Role:** guide
**Status:** current; the web interface is not built yet
([`docs/plans/plan.md`](docs/plans/plan.md) § 4)
**Authority:** the trust boundary and how to report a problem

femkit is a single-user tool. It runs as the person who starts it, with that
person's permissions, on their workstation or in their cluster account.

- **femkit stores no credential.** SSH keys, scheduler credentials and tokens
  stay in the person's own configuration, and none appears in a committed file
  ([`config.md`](docs/contracts/config.md) § 1).
- **Commands are built, not passed through.** Every outside command is an
  argument vector, never a shell string, assembled from declared definitions
  and validated requests ([`core.md`](docs/contracts/core.md) § 8).
- **Downloads are pinned.** Every source archive is fetched by URL and checked
  against its declared SHA-256 before it is unpacked
  ([`envs.md`](docs/contracts/envs.md) § 4.1).
- **The web interface, when built, binds to loopback by default**; serving it
  beyond the machine requires TLS and authentication.

## Reporting a problem

Report a suspected command injection, path traversal, unsafe file permission or
credential exposure privately, through the repository's security advisories
("Report a vulnerability" on GitHub), before publishing details.
