# Security policy

## Reporting a vulnerability

Please don't open a public issue. Report it privately through GitHub: on the repository's **Security** tab, choose **Report a vulnerability** ([direct link](https://github.com/Horus-EIP/horus-bench-kit/security/advisories/new)). Only the maintainers see the report.

Say what is affected, how to reproduce it, and what an attacker could do with it. We answer within a week, keep you informed while we fix it, and credit you in the advisory unless you would rather not be named.

## Supported versions

Fixes go into the latest release only. Update to it before you report.

## Scope

In scope: anything in this repository, for example a test set, catalog, report or probe item that makes a tool write outside the folder it was given, run a command it should not, or reveal the API key read from `--api-key-env`.

Out of scope: the servers, models and container images that the kit runs or queries at your request, and the probe programs you write yourself, which the kit runs by design.
