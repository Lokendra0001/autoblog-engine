# AutoBlog Engine

**Your SEO blog on autopilot: researched, written and published for you.**

[![tests](https://github.com/navigotechsolutions-labs/autonomous-seo-writer/actions/workflows/tests.yml/badge.svg)](https://github.com/navigotechsolutions-labs/autonomous-seo-writer/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

AutoBlog Engine writes and publishes blog articles for your business by itself, on the days you
choose, using free services only.

## How it works

It checks once a day. Here's what happens and which key each step uses:

**Once a month: plan the topics**

| Step | Uses |
|---|---|
| Find what your customers search for on Google | Google suggestions (no key) |
| Read the posts already on your site, so nothing repeats | `STRAPI_API_TOKEN` |
| Pick the month's topics and dates | `GEMINI_API_KEY` |
| Email you the plan | `RESEND_API_KEY` |

**On each publish day: write one article**

| Step | Uses |
|---|---|
| Check this week's news; one article a month can cover important news (`max_news_per_month`) | Google News (no key) + `GEMINI_API_KEY` |
| Research the topic: real questions, research papers, news, background | Google, Wikipedia (no key), OpenAlex (`OPENALEX_API_KEY`, free) |
| Write the article | `GEMINI_API_KEY` |
| Check it: SEO rules plus an AI editor score; rewrite up to 3 times if needed | `GEMINI_API_KEY` |
| Add a cover photo and 2 images | `UNSPLASH_ACCESS_KEY` |
| Upload it as a draft (or publish it) | `STRAPI_API_TOKEN` (or WordPress) |
| Email you a link to review it | `RESEND_API_KEY` |

Only Gemini and Unsplash are required. Without an OpenAlex key, articles just skip research papers. Without a CMS token, articles are just saved as files.
Without Resend, it simply doesn't send emails. One article uses about 4 to 10 Gemini requests.

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
docker compose run --rm writer python cli.py run-next mybusiness # test the full daily job now
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
