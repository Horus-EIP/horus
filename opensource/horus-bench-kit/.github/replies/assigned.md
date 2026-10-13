Thanks @{user}, issue #{issue} is yours. Here is how to go on:

1. Fork the repository and create a branch named `{issue}-<short-name>`.
2. Follow the commit norm in [CONTRIBUTING.md](https://github.com/Horus-EIP/horus-bench-kit/blob/main/CONTRIBUTING.md) (`[+]`, `[~]`, `[x]`, `[-]`, `[#]`, `[?]`) and sign off every commit with `git commit -s`.
3. Install the kit with `pip install -e ".[test]"` and run `pytest`.
4. Open a pull request that says `Fixes #{issue}`. A draft is fine.

The rules: open a draft pull request within {reminder_days} days, hold at most {limit} claimed issues at a time, and comment `/unassign` to give an issue back. After {release_days} days without activity from you, the issue is unassigned so that someone else can take it.
