# Issue tracker: GitHub

Repository: `JoshuaOliphant/forkhub`. GitHub Issues are enabled, verified through
`gh api repos/JoshuaOliphant/forkhub` on 2026-11-10. Existing labels are `bug`,
`documentation`, `duplicate`, `enhancement`, `good first issue`, `help wanted`,
`invalid`, `question`, and `wontfix`. This verification setup creates no labels.

Read issues with GitHub REST, because GraphQL authentication is unavailable in
this session:

```sh
gh api repos/JoshuaOliphant/forkhub/issues/35
gh api repos/JoshuaOliphant/forkhub/issues/35/comments --paginate
```

Rulings, review outcomes and acceptance tables belong on their issue. The bulk
test-node cache is [acceptance.md](acceptance.md), including rows for closed issues.
Publish tables with marker `<!-- forkhub-acceptance -->`; the verifier checks
their edit timestamps using one paginated issue-comment listing.

Commits and pull requests reference the owning issue. Do not close an issue or
merge a pull request merely because verification passed. Production deployment,
existing-database writes and messages outside the invoked workflow require their
own authorization.
