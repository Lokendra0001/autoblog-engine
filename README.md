# AutoBlog Engine

**Your SEO blog on autopilot: researched, written and published for you.**

[![tests](https://github.com/navigotechsolutions-labs/autonomous-seo-writer/actions/workflows/tests.yml/badge.svg)](https://github.com/navigotechsolutions-labs/autonomous-seo-writer/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

AutoBlog Engine writes and publishes blog articles for your business by itself. Every month it:

1. finds what your customers search for on Google,
2. plans the topics (skipping anything already on your site),
3. researches each topic and writes the article,
4. checks the quality and rewrites it if needed,
5. publishes it on your chosen days and emails you.

It uses free services only (Gemini, Unsplash, Google search, Resend).

## Getting started

You need [Docker](https://docs.docker.com/get-docker/) and two free keys:
[Gemini](https://aistudio.google.com/apikey) and [Unsplash](https://unsplash.com/developers).

**1. Download it**

```bash
git clone https://github.com/navigotechsolutions-labs/autonomous-seo-writer.git
cd autonomous-seo-writer
```

**2. Add your keys**

```bash
cp .env.example .env
```

Open `.env` and paste your `GEMINI_API_KEY` and `UNSPLASH_ACCESS_KEY`.

**3. Describe your business**

```bash
cp -r clients/_template clients/mybusiness
```

Open `clients/mybusiness/config.yaml` and fill it in: your company, products, customers and website
links. Every line is explained in the file. When you're done, set `enabled: true`.

**4. Start it**

```bash
docker compose up -d --build
```

That's it. It now runs every day and writes articles on the planned days.
Check it's running with `docker compose logs writer`.

## Where articles go

Choose with `publish_to` in your config:

- `files`: only saved, not published (the default, good for testing)
- `strapi`: uploaded to your Strapi website
- `wordpress`: posted to your WordPress website

Uploads go in as **drafts** by default, so you can review before they go live. The setup for each
is explained in the config file.

## See your articles

Set `CLIENT=mybusiness` in `.env`, then run:

```bash
docker compose --profile web up -d
```

Open http://127.0.0.1:8000 to see the monthly plan and every article, or to write one now.

## Common settings (`.env`)

| Setting | Example | Meaning |
|---|---|---|
| `POSTS_PER_MONTH` | `8` | How many articles a month |
| `PUBLISH_DAYS` | `tue,fri` | Which days to post |
| `SCHEDULE_TIME` | `09:07` | What time it runs each day |
| `PUBLISH_TO` | `files` | Overrides `publish_to` for all businesses |
| `NOTIFY_TO` | `you@example.com` | Where to send email updates (needs a free Resend key) |

After changing `.env` or the config, run `docker compose up -d --force-recreate`.

## Useful commands

```bash
docker compose logs -f writer      # see what it's doing
docker compose down                # stop it
git pull && docker compose up -d --build                         # update to the latest version
docker compose run --rm writer python cli.py validate mybusiness # check your setup
docker compose run --rm writer python cli.py run mybusiness      # write one article now
```

## Without Docker

```bash
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/python cli.py validate mybusiness
./venv/bin/python cli.py schedule on    # runs it daily
```

## Good to know

- It never writes the same topic twice, and never uploads something already on your site.
- The free Gemini plan is enough for about 2 articles a week. If it's busy, the article waits for the next day.
- Your keys stay in `.env`, which is never uploaded to GitHub.

## License

MIT. Free to use and change. See [LICENSE](LICENSE).
