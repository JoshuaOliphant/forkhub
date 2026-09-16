# Agent Instructions

This project uses **GitHub Issues** for issue tracking.

Browse open issues: https://github.com/JoshuaOliphant/forkhub/issues

For the full project guide (architecture, testing, patterns), see `CLAUDE.md`.

Historical note: This project previously used beads for local issue tracking.
See `docs/beads-migration.md` for the migration map from bead IDs to GitHub issue numbers.

## GitHub Issues Quick Reference

Use the `gh` CLI for issue operations:

```bash
# Find work
gh issue list                          # List open issues
gh issue list --assignee @me           # Issues assigned to you
gh issue list --label bug              # Filter by label
gh issue view <number>                 # View issue details

# Create issues
gh issue create --title "Title" --body "Description"
gh issue create --title "Title" --label bug --label P1

# Update issues
gh issue edit <number> --add-label "in-progress"
gh issue close <number> --comment "Done in commit abc123"

# Link issues to PRs
# Reference in commit: "Fix auth bug (#42)"
# Reference in PR body: "Closes #42" or "Fixes #42"
```

### Issue Labels

| Label | Use for |
|-------|---------|
| `bug` | Something broken |
| `enhancement` | New functionality |
| `documentation` | Docs improvements |
| `P0`-`P3` | Priority (0=critical, 3=low) |

## Session Completion

**When ending a work session**, complete ALL steps below:

1. **File issues for remaining work** — Create GitHub issues for anything that needs follow-up:
   ```bash
   gh issue create --title "Follow-up: <description>" --body "Context from this session"
   ```

2. **Run quality gates** (if code changed):
   ```bash
   uv run pytest --cov=src/forkhub -m "not integration and not slow"
   uv run ruff check src/ tests/
   uv run ruff format --check src/ tests/
   ```

3. **Push to remote** — This is mandatory:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```

4. **Hand off** — Provide context for next session

**Critical rules:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing — that leaves work stranded locally
- If push fails, resolve and retry until it succeeds

## Non-Interactive Shell Commands

**ALWAYS use non-interactive flags** with file operations to avoid hanging on confirmation prompts.

Shell commands like `cp`, `mv`, and `rm` may be aliased to include `-i` (interactive) mode on some systems, causing the agent to hang indefinitely waiting for y/n input.

**Use these forms instead:**
```bash
# Force overwrite without prompting
cp -f source dest           # NOT: cp source dest
mv -f source dest           # NOT: mv source dest
rm -f file                  # NOT: rm file

# For recursive operations
rm -rf directory            # NOT: rm -r directory
cp -rf source dest          # NOT: cp -r source dest
```

**Other commands that may prompt:**
- `scp` - use `-o BatchMode=yes` for non-interactive
- `ssh` - use `-o BatchMode=yes` to fail instead of prompting
- `apt-get` - use `-y` flag
- `brew` - use `HOMEBREW_NO_AUTO_UPDATE=1` env var
