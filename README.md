# SEO Content Agent

A **multi-tenant, sellable** version of the NaviGo blog automation. The same proven
pipeline — discover trending keywords → research → draft a full SEO blog → generate
branded images → auto-publish to WordPress → inject schema → index — but every
brand-specific value is **per-client config**, so one engine serves many clients.

See [PRODUCT_PLAN.md](PRODUCT_PLAN.md) for the productization, pricing and roadmap.

## Why this is separate from `ai-wordpress-agent/`

The original lives on a live VPS cron and is marked read-only (its `CLAUDE.md`).
This package leaves it fully intact and re-implements the logic in a config-driven
form. NaviGo is included as **tenant #1** (`clients/navigo/`) so it can run here too.

## Layout

```
agent/        config-driven engine (ai, trends, research, writer, images,
              publisher, indexer, state, pipeline, runner)
clients/      one folder per client: config.yaml + assets/logo.png
  _template/  copy-to-onboard schema, every field documented
  navigo/     NaviGo Tech Solutions
data/<id>/    runtime state per client (used topics, drafts, published log)
cli.py        list | validate | run | run-all | add-client
```

## Setup

```bash
cd seo-content-agent
python -m venv venv && venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env                                 # fill in API keys + WP creds
```

## Use

```bash
python cli.py list                       # show clients + enabled state
python cli.py validate navigo            # check WP auth, sitemap, logo
python cli.py run navigo --dry-run       # generate a draft to data/navigo/drafts/ (no publish)
python cli.py run navigo                 # generate AND publish one post
python cli.py run-all                    # service every enabled client (use in cron)
```

## Onboard a new client

```bash
python cli.py add-client acme            # scaffolds clients/acme/ from _template
# edit clients/acme/config.yaml, drop clients/acme/assets/logo.png
python cli.py validate acme
python cli.py run acme --dry-run         # client reviews the HTML draft
# set enabled: true in config.yaml  -> picked up by run-all
```

## Scheduling

Point a cron / Windows Task at:

```bash
python cli.py run-all
```

Each client's `topic_mode` (`trending` | `breaking` | `evergreen_queue`) and
`posts_per_day` control what and how much it posts.

> **Note:** NaviGo's tenant ships `enabled: false` so it won't double-post against
> the live VPS cron. Flip it to `true` only when this engine takes over posting.
