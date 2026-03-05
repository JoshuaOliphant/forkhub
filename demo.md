# ForkHub Demo — Monitoring GitHub Fork Constellations

*2026-03-05T17:16:46Z by Showboat 0.6.1*
<!-- showboat-id: a9a0d7ea-53cd-4bc0-91a7-e7ada4e890de -->

ForkHub monitors the constellation of forks around your GitHub repositories, uses AI to classify what changed, and surfaces interesting divergences. Let's take it for a spin.

## Installation

```bash
uv run forkhub --version
```

```output
forkhub 0.1.0
```

ForkHub is installed and ready. It uses `uv` for package management — all commands run through `uv run forkhub`.

## Seeing What's Available

ForkHub has already been initialized with a GitHub account. Let's see what repositories are being tracked.

```bash
uv run forkhub repos
```

```output
                              Tracked Repositories                              
┏━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Repository              ┃ Mode  ┃ Description             ┃ Last Synced      ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ JoshuaOliphant/claude-… │ owned │ Claude Code plugin      │ 2026-03-05 17:07 │
│                         │       │ marketplace -           │                  │
│                         │       │ productivity and        │                  │
│                         │       │ learning plugins        │                  │
│ JoshuaOliphant/herald   │ owned │ Telegram gateway to     │ 2026-03-05 17:07 │
│                         │       │ Claude Code for mobile  │                  │
│                         │       │ access to your second   │                  │
│                         │       │ brain                   │                  │
│ JoshuaOliphant/obsidia… │ owned │ MCP server for querying │ 2026-03-05 17:07 │
│                         │       │ Obsidian vault graph    │                  │
│                         │       │ data — backlinks,       │                  │
│                         │       │ orphans, broken links,  │                  │
│                         │       │ and more                │                  │
│ JoshuaOliphant/reading… │ owned │ Test application        │ 2026-03-05 17:07 │
│                         │       │ exploring the hexagonal │                  │
│                         │       │ agent architecture      │                  │
│                         │       │ pattern - AI agents     │                  │
│                         │       │ generate HTMX UI via    │                  │
│                         │       │ ports-and-adapters      │                  │
│                         │       │ design                  │                  │
│ JoshuaOliphant/exa-sea… │ owned │ Search the web using    │ 2026-03-05 17:07 │
│                         │       │ Exa's AI-powered        │                  │
│                         │       │ search. Get relevant    │                  │
│                         │       │ results instantly with  │                  │
│                         │       │ real-time or manual     │                  │
│                         │       │ search modes.           │                  │
│ JoshuaOliphant/jean-cl… │ owned │ Universal AI Developer  │ 2026-03-05 17:07 │
│                         │       │ Workflows - CLI for     │                  │
│                         │       │ programmatic Claude     │                  │
│                         │       │ Code orchestration      │                  │
│ JoshuaOliphant/mochi_d… │ owned │ AI-powered spaced       │ 2026-03-05 17:07 │
│                         │       │ repetition learning     │                  │
│                         │       │ tool that converts      │                  │
│                         │       │ content into            │                  │
│                         │       │ high-quality flashcards │                  │
│                         │       │ following Andy          │                  │
│                         │       │ Matuschak's principles  │                  │
│ JoshuaOliphant/Plant-D… │ owned │ -                       │ 2026-03-05 17:07 │
│ JoshuaOliphant/avocet   │ owned │ A bookmark manager that │ 2026-03-05 17:07 │
│                         │       │ interacts with the      │                  │
│                         │       │ raindrop.io API, built  │                  │
│                         │       │ with the Python Textual │                  │
│                         │       │ TUI framework.          │                  │
│ JoshuaOliphant/digital… │ owned │ -                       │ 2026-03-05 17:07 │
│ JoshuaOliphant/Link-Co… │ owned │ A FastAPI web           │ 2026-03-05 17:07 │
│                         │       │ application that        │                  │
│                         │       │ scrapes content from    │                  │
│                         │       │ web pages and their     │                  │
│                         │       │ linked pages,           │                  │
│                         │       │ converting them to      │                  │
│                         │       │ clean markdown format   │                  │
│                         │       │ using the Jina Reader   │                  │
│                         │       │ API.                    │                  │
│ JoshuaOliphant/openapi… │ owned │ The OpenAPI Click CLI   │ 2026-03-05 17:07 │
│                         │       │ Generator is a Python   │                  │
│                         │       │ application that        │                  │
│                         │       │ automatically generates │                  │
│                         │       │ a command-line          │                  │
│                         │       │ interface (CLI) from an │                  │
│                         │       │ OpenAPI specification.  │                  │
│                         │       │ The generated CLI       │                  │
│                         │       │ allows easy interaction │                  │
│                         │       │ with the API defined in │                  │
│                         │       │ the OpenAPI spec,       │                  │
│                         │       │ leveraging Python's     │                  │
│                         │       │ Click library.          │                  │
│ JoshuaOliphant/mc_logg… │ owned │ -                       │ 2026-03-05 17:07 │
│ JoshuaOliphant/claude-… │ owned │ AI-powered resume       │ 2026-03-05 17:07 │
│                         │       │ customization tool      │                  │
│                         │       │ using Claude Code SDK   │                  │
│ JoshuaOliphant/scratch… │ owned │ MCP server providing a  │ 2026-03-05 17:07 │
│                         │       │ 'think' tool for        │                  │
│                         │       │ structured reasoning    │                  │
│ JoshuaOliphant/grosbeak │ owned │ This project is an      │ 2026-03-05 17:07 │
│                         │       │ AI-powered resume       │                  │
│                         │       │ customization system    │                  │
│                         │       │ that tailors a          │                  │
│                         │       │ candidate's resume to a │                  │
│                         │       │ specific job            │                  │
│                         │       │ description. It         │                  │
│                         │       │ utilizes multiple data  │                  │
│                         │       │ sources, including the  │                  │
│                         │       │ candidate's existing    │                  │
│                         │       │ resume, LinkedIn        │                  │
│                         │       │ profile, and GitHub     │                  │
│                         │       │ profile, to create a    │                  │
│                         │       │ comprehensive and       │                  │
│                         │       │ tailored resume.        │                  │
│ JoshuaOliphant/ResumeA… │ owned │ -                       │ 2026-03-05 17:07 │
│ JoshuaOliphant/test     │ owned │ -                       │ 2026-03-05 17:07 │
│ JoshuaOliphant/starling │ owned │ An application for      │ 2026-03-05 17:07 │
│                         │       │ S.T.A.R. interview      │                  │
│                         │       │ question practice.      │                  │
│ JoshuaOliphant/RockS.T… │ owned │ An AI interview         │ 2026-03-05 17:07 │
│                         │       │ practice assistant      │                  │
│ JoshuaOliphant/ResumeR… │ owned │ -                       │ 2026-03-05 17:07 │
│ JoshuaOliphant/resumas… │ owned │ Customize your resume   │ 2026-03-05 17:07 │
│ JoshuaOliphant/face_sh… │ owned │ A web app to identify   │ 2026-03-05 17:07 │
│                         │       │ male face shapes for    │                  │
│                         │       │ haircuts                │                  │
│ JoshuaOliphant/entiendo │ owned │ An application to help  │ 2026-03-05 17:07 │
│                         │       │ understand complex      │                  │
│                         │       │ documents.              │                  │
│ JoshuaOliphant/chickad… │ owned │ This project analyzes   │ 2026-03-05 17:07 │
│                         │       │ ChatGPT conversations   │                  │
│                         │       │ to extract and refine   │                  │
│                         │       │ prompts, providing      │                  │
│                         │       │ insights into common    │                  │
│                         │       │ themes and patterns in  │                  │
│                         │       │ user queries. It uses   │                  │
│                         │       │ OpenAI's GPT-4o model   │                  │
│                         │       │ to process the          │                  │
│                         │       │ conversations and       │                  │
│                         │       │ generate reusable       │                  │
│                         │       │ prompts.                │                  │
│ JoshuaOliphant/app_gen… │ owned │ A backend Python code   │ 2026-03-05 17:07 │
│                         │       │ generator, with a       │                  │
│                         │       │ Claude agent at         │                  │
│                         │       │ coordinating the        │                  │
│                         │       │ generated API and       │                  │
│                         │       │ integrations via tool.  │                  │
│ JoshuaOliphant/JoshuaO… │ owned │ -                       │ 2026-03-05 17:07 │
│ JoshuaOliphant/An-Olip… │ owned │ -                       │ 2026-03-05 17:07 │
│ JoshuaOliphant/field_g… │ owned │ -                       │ 2026-03-05 17:07 │
│ JoshuaOliphant/docqa_b… │ owned │ -                       │ 2026-03-05 17:07 │
│ JoshuaOliphant/rockin-… │ owned │ -                       │ 2026-03-05 17:07 │
│ JoshuaOliphant/fish-sh… │ owned │ List of kubectl aliases │ 2026-03-05 17:08 │
│                         │       │ used with fish shell    │                  │
│ JoshuaOliphant/Drafts-… │ owned │ A Drafts Action that    │ 2026-03-05 17:08 │
│                         │       │ automates the sending   │                  │
│                         │       │ from Drafts to a Jekyll │                  │
│                         │       │ site hosted in Github   │                  │
│ JoshuaOliphant/contact… │ owned │ An app for learning     │ 2026-03-05 17:08 │
│                         │       │ first web 1.0 style web │                  │
│                         │       │ applications, and then  │                  │
│                         │       │ transforming it to use  │                  │
│                         │       │ htmx                    │                  │
│ JoshuaOliphant/kafka-h… │ owned │ A Kafka producer with   │ 2026-03-05 17:08 │
│                         │       │ htmx                    │                  │
└─────────────────────────┴───────┴─────────────────────────┴──────────────────┘
```

35 repositories tracked across the account. All were auto-discovered during `forkhub init`. Now let's look at the configuration.

## Configuration

ForkHub supports three config sources: TOML files, environment variables, and dotenv files. Env vars always win. Let's see the current config.

```bash
uv run forkhub config show
```

```output
ForkHub Configuration

GitHub
  token: gith...puag
  username: joshuaoliphant

Anthropic
  auth: OAuth token (sk-ant-o...)
  analysis_budget_usd: 0.5
  model: sonnet
  digest_model: haiku

Database
  path: ~/.local/share/forkhub/forkhub.db

Sync
  polling_interval: 6h
  max_forks_per_repo: 5000

Analysis
  max_deep_dives_per_fork: 10

Embedding
  provider: local
  model: all-MiniLM-L6-v2

Digest
  frequency: weekly
  min_significance: 5
  backends: console
```

Tokens are loaded from the dotenv file automatically. Notice both GitHub and Anthropic auth are configured — ForkHub supports either API keys or OAuth tokens from `claude set-token`.

## Exploring Forks

Let's look at a repo that has forks. The `forks` command shows discovered forks for a tracked repo.

```bash
uv run forkhub forks JoshuaOliphant/grosbeak
```

```output
                            Forks                             
┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┓
┃ Fork                   ┃ Stars ┃ Ahead ┃ Behind ┃ Vitality ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━━━━┩
│ mvandermeulen/grosbeak │     0 │     0 │      0 │ dead     │
└────────────────────────┴───────┴───────┴────────┴──────────┘
```

One fork discovered for grosbeak (an AI-powered resume customizer). The `vitality` column classifies fork activity: `active`, `dormant`, or `dead`. This fork has 0 commits ahead, so it's a bare fork with no changes — classified as dead.

## Tracking External Repos

You can also track repos you don't own. Let's track a popular repo and sync its forks.

```bash
uv run forkhub track anthropics/claude-code
```

```output
Tracked anthropics/claude-code (mode: watched, depth: 1)
```

Now tracked in **watched** mode. Let's sync just this repo to discover its forks.

```bash
uv run forkhub sync --repo anthropics/claude-code
```

```output
Syncing anthropics/claude-code...

Sync complete for anthropics/claude-code:
  New forks discovered: 5009
  Changed forks: 0
  New releases: 30
```

5,009 forks discovered and 30 releases tracked. That's a popular repo\! Let's see some of those forks.

```bash
uv run forkhub forks anthropics/claude-code | head -30
```

```output
                                     Forks                                      
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┓
┃ Fork                                     ┃ Stars ┃ Ahead ┃ Behind ┃ Vitality ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━━━━┩
│ doggy8088/claude-code                    │    23 │     0 │      0 │ active   │
│ zhimin-z/claude-code                     │     9 │     0 │      0 │ active   │
│ huan11/claude-code                       │     8 │     0 │      0 │ dormant  │
│ InflixOP/claude-code                     │     8 │     0 │      0 │ dormant  │
│ fabriziosalmi/claude-code-brutal-edition │     7 │     0 │      0 │ dormant  │
│ parvin528/claude-code                    │     4 │     0 │      0 │ dormant  │
│ tanzinabd23/claude-code                  │     4 │     0 │      0 │ dormant  │
│ SMSDAO/castquest-code                    │     3 │     0 │      0 │ active   │
│ mattpocock/claude-code                   │     3 │     0 │      0 │ active   │
│ sheikhsajid69/claude-code                │     3 │     0 │      0 │ active   │
│ goo-goo-gaga/claude-code                 │     3 │     0 │      0 │ active   │
│ Nutlope/claude-code                      │     3 │     0 │      0 │ active   │
│ delikat/claude-code                      │     3 │     0 │      0 │ active   │
│ 0xinf0/claude-code                       │     3 │     0 │      0 │ active   │
│ tilltmk/ollama-code                      │     3 │     0 │      0 │ dormant  │
│ Alexandre-Santos-Lima/claude-code        │     2 │     0 │      0 │ active   │
│ RichardTang-Aden/claude-code             │     2 │     0 │      0 │ active   │
│ open-inf/claude-code                     │     2 │     0 │      0 │ active   │
│ samofoke/claude-code                     │     2 │     0 │      0 │ active   │
│ ndbroadbent/claude-code                  │     2 │     0 │      0 │ active   │
└──────────────────────────────────────────┴───────┴───────┴────────┴──────────┘
```

Forks are sorted by stars. Notice the vitality classification — `active` forks have recent commits, `dormant` forks haven't been touched recently, and `dead` forks have no changes at all. Some interesting names in there: `claude-code-brutal-edition`, `castquest-code`, `ollama-code` — these are the kind of divergences ForkHub is designed to surface.

## Inspecting a Fork

Let's inspect one of the more interesting forks to see what it's doing.

```bash
uv run forkhub inspect fabriziosalmi/claude-code-brutal-edition
```

```output
fabriziosalmi/claude-code-brutal-edition
  Description: Brutalize the codebase from the beginning.
  Stars: 7
  Vitality: dormant
  Commits ahead: 0
  Commits behind: 0
  Default branch: main
  HEAD SHA: -

  No signals recorded for this fork.
```

"Brutalize the codebase from the beginning." — now that's a fork description. No signals yet because we haven't run the AI analysis pipeline. Signals are generated when the Claude agent inspects what changed in each fork.

## Using ForkHub as a Library

ForkHub is a library first — the CLI is just a thin consumer. Here's the same operations via the Python API.

```bash
uv run python3 -c "
import asyncio
from forkhub import ForkHub

async def main():
    async with ForkHub() as hub:
        repos = await hub.get_repos()
        print(f\"Tracking {len(repos)} repositories\")

        forks = await hub.get_forks(\"anthropics\", \"claude-code\", active_only=True)
        print(f\"Active forks of claude-code: {len(forks)}\")

        top = sorted(forks, key=lambda f: f.stars, reverse=True)[:5]
        for f in top:
            print(f\"  {f.full_name} ({f.stars} stars, {f.vitality})\")

asyncio.run(main())
"
```

```output
Tracking 36 repositories
Active forks of claude-code: 3074
  doggy8088/claude-code (23 stars, active)
  zhimin-z/claude-code (9 stars, active)
  SMSDAO/castquest-code (3 stars, active)
  mattpocock/claude-code (3 stars, active)
  sheikhsajid69/claude-code (3 stars, active)
```

The same data is accessible programmatically. ForkHub is an async context manager — all operations use `async/await`. The library returns Pydantic models, making it easy to filter, sort, and process data in custom pipelines.

## Test Suite

ForkHub has a comprehensive test suite covering the full stack — config, database, providers, services, agent layer, CLI, and public API.

```bash
uv run pytest -q --tb=no 2>&1 | tail -3
```

```output
........................................................................ [ 95%]
...................                                                      [100%]
450 passed, 1 skipped in 70.42s (0:01:10)
```

450 tests passing, 1 skipped (an integration test requiring live API keys). The test suite uses real stub classes that conform to the Protocol interfaces — no `unittest.mock` anywhere.

```bash
uv run ruff check src/ tests/
```

```output
All checks passed!
```

## Cleanup

Let's untrack the claude-code repo we added for this demo.

```bash
uv run forkhub untrack anthropics/claude-code
```

```output
Untracked anthropics/claude-code
```

---

ForkHub is open source at [github.com/JoshuaOliphant/forkhub](https://github.com/JoshuaOliphant/forkhub). It's a Python library first, CLI second — designed so future consumers (web UI, GitHub Action) can build on the same foundation.
