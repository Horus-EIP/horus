## 📌 Task & Issue Tracking

All work must be associated with a GitHub **Issue**. No issue = no code.

### 🛠️ Task Rules

1. **Create a GitHub Issue** before you start any task.
2. **Create a Branch from that Issue** using:
   ```
   issue-<issue-number>-<short-description>
   ```

   _Example: `issue-42-agent-routing`_
3. **Assign yourself** to the issue.
4. **Estimate time** required (e.g., `2h`, `1d`, `3d`).
5. **Work only in that branch**, and reference the issue in your commits and PRs.
6. **Open a Pull Request**, link the issue with:
   ```
   Fixes #<issue-number>
   ```
7. **Get 2 reviewers from the group who DID NOT write the code**.
8. **Only merge after 2 approvals.**
9. **Use Squash & Merge**, then delete the branch.
10. **Issue closes automatically** if `Fixes #` is used, else close it manually.

### 📋 Example Issue Template

```
Title: [Core] Implement communication handler

Description:
Create a core handler that routes messages between AI agents using internal protocol.

Estimate: 1d  
Assignee: @yourusername  
Labels: enhancement, AI  
Milestone: MVP v1  
```
