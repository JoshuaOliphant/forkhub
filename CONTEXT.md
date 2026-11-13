# ForkHub domain language

## Glossary

- **Repository:** a GitHub repository identified by its stable provider ID; its name can change.
- **Discovery attempt:** one effort to observe repositories, relationships, forks, or releases. An attempt can fail or have incomplete coverage.
- **Snapshot:** persisted observations from discovery. A saved complete relationship snapshot can outlive an incomplete refresh.
- **Comparison:** observed differences between identified source and target revisions. A push timestamp is a change hint, not comparison evidence.
- **Analysis:** interpretation of observed changes. Completing discovery does not establish completion of analysis.
- **Signal:** a persisted interpretation of a source change, with significance and optional immutable evidence.
- **Evidence:** recorded source identity, cited commit SHAs, relevant changes, and content-verification state. Verified content does not verify an interpretation or successful adoption.
- **Backfill attempt:** an execution that tries to adopt a signal's changes in a local repository. Previewing is distinct from executing an attempt.
- **Candidate branch:** a branch created for a backfill attempt. Knowing a branch name does not establish ownership.
- **Test result:** the outcome of a particular test execution against a particular revision. It is distinct from a human decision to accept a candidate.
- **Cluster:** derived grouping of related signals. An embedding is input to grouping, not evidence that grouping completed.
- **Delivery:** sending a generated digest to one configured destination. Attempting delivery does not establish success.
- **Freshness:** when observations or analysis were obtained, and whether a subsequent attempt failed. Freshness is separate from coverage and evidence verification.

## Semantic invariants

- Missing evidence is unknown, not proof of absence or successful processing.
- A model interpretation is not independently verified merely because its cited content is verified.
- Discovery completion, analysis completion, evidence verification, test success, and delivery success describe different facts.
- An incomplete relationship refresh does not erase the last complete saved snapshot.
- Website and MCP consume the same core intelligence and preserve the same evidence limitations.
- A branch name alone does not establish that a backfill attempt created or owns that branch.
