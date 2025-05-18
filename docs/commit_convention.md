
# 🧾 Git Commit Convention

To maintain a clean and understandable Git history, all commits in this repository must follow a standard format.

## ✅ Format

```
[SYMBOL] Short Title

Longer explanation of what was done, why it was done, and how (if necessary).
```

## 🔣 Symbols & Meanings

| Symbol | Meaning                   | Use when...                                               |
|--------|---------------------------|------------------------------------------------------------|
| [+]    | Add                       | Adding a new file, feature, class, or functionality        |
| [~]    | Update / Modify / Refactor| Updating or refactoring existing code                     |
| [x]    | Fix                       | Fixing a bug, typo, or issue                              |
| [-]    | Remove                    | Deleting code, files, or deprecated features              |
| [!]    | Important / Breaking      | Introducing breaking changes or hotfixes                  |
| [#]    | Docs / Comment            | Updating README, markdown, or inline comments             |
| [>]    | Performance / Optimization| Improving speed, memory, or efficiency                    |
| [?]    | Work In Progress (WIP)    | Committing unfinished or experimental code                |

## 🧠 Description Guidelines

- Use present tense in titles (e.g., "Add login module")
- Be short and clear in the title
- Provide context in the description when useful

## 💡 Example

```
[+] Add multi-agent orchestrator for Horus

Implemented a Python orchestrator module to manage inter-agent communication via RPC. Enables task delegation and supports modular agent plugins.
```
