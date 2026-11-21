# AutoBlog Engine

**Your SEO blog on autopilot: researched, written and published for you.**

[![tests](https://github.com/navigotechsolutions-labs/autonomous-seo-writer/actions/workflows/tests.yml/badge.svg)](https://github.com/navigotechsolutions-labs/autonomous-seo-writer/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

We built AutoBlog Engine to run a company blog without anyone sitting down to write it. Every month it plans
a set of topics from real Google searches, researches each one, writes the article, checks it, and
uploads it to the website on the days you choose. You get an email each time something happens.

It runs on free tiers only: Gemini for writing, Unsplash for photos, Google search suggestions for
keywords, OpenAlex, Google News and Wikipedia for research, and Resend for email.

One install can handle several businesses. Each one is a single config file.

## What it does

1. **Plans the month.** It expands your core keywords into the searches people actually type, then
   picks a mix of topics. Anything already on your site is skipped.
2. **Researches each topic.** Real search questions, recent research papers, news from the last
   year and some background. The writer is only allowed to use figures from this research or from
   the facts you give it about your business.
3. **Writes and checks.** Every draft goes through rule checks (title, meta description, keyword
   placement, length, table, FAQs, internal links) and an AI editor that scores it out of 10. Below 8,
   it gets rewritten, up to three drafts, and the best one is kept.
4. **Finishes it.** Adds matching stock photos, your call-to-action box and FAQ schema for Google.
5. **Publishes it** to Strapi or WordPress, as a draft for review or live straight away. Or it
   just saves the files if you'd rather post by hand.

Every article is also saved in `data/<client>/drafts/` as a preview page (`.html`), the raw fields
(`.json`) and the cover image (`.jpg`).

## Getting started

You need Python 3.10+ (or Docker, see below) and two free API keys:

- Gemini: https://aistudio.google.com/apikey
- Unsplash: https://unsplash.com/developers (create an app and copy its Access Key)

```bash
git clone https://github.com/navigotechsolutions-labs/autonomous-seo-writer.git
cd autonomous-seo-writer
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
cp .env.example .env        # put your two keys in here
```

Then set up your business:

```bash
./venv/bin/python cli.py add-client acme      # creates clients/acme/config.yaml
```

Open `clients/acme/config.yaml` and fill it in. Every setting has a comment, and the file uses a
made-up solar company as an example, so you can see what goes where. The parts that matter most:

- `context`: facts about your products and services. Be specific. The writer won't claim anything
  about you that isn't here.
- `audience`, `categories`, `internal_links`, `cta`
- `sources.keyword_seeds`: three to six terms your customers search for
- `writing_notes`: any rules for your field, like "never quote prices"

Check it and write a test article:

```bash
./venv/bin/python cli.py validate acme
./venv/bin/python cli.py run acme --dry-run --keyword "your main topic"
```

The preview opens in your browser. Once you're happy, set `enabled: true` in the config and
put it on a schedule.

## Where articles go

Set `publish_to` in the client config:

| Value | Result |
|---|---|
| `strapi` | Uploaded to your Strapi (v5) site |
| `wordpress` | Posted to your WordPress site |
| `files` | Not published anywhere, only saved in `data/<client>/drafts/` |

If you leave it empty, it uses whichever CMS you've filled in, and falls back to `files`.
`PUBLISH_TO` in `.env` overrides the config, so `PUBLISH_TO=files` is a quick way to pause publishing.

`python cli.py validate <client>` tells you which one it will use.

### Strapi

1. In the Strapi admin, go to **Settings → API Tokens** and create a Custom token with these
   permissions: `find`, `findOne`, `create` and `update` on your blog collection, and `upload` under
   Upload.
2. Put it in `.env` as `STRAPI_API_TOKEN`.
3. In the config, fill in `strapi.url`, `strapi.collection` (the API name, e.g. `blogs`) and
   `strapi.status` (`draft` or `published`).
4. If your fields have different names, map them under `strapi.fields`. Set a field to `""` to skip it.
   The content is HTML, so it needs a Rich text or long text field that your site renders as HTML.

Before writing anything, it reads your existing posts (drafts included) and won't write or upload a
topic that's already there. If Strapi can't be reached, it holds the upload and tries again the next day.

### WordPress

Create an Application Password under **Users → Profile**, add it to `.env`, and fill in the
`wordpress` section of the config. `status` can be `draft` or `publish`.

## Running it on a schedule

### With Docker (easiest on a server)

```bash
cp .env.example .env         # fill it in
docker compose up -d --build
docker compose logs -f writer
```

The log should end with something like `Next run: Tue 24 Nov 2026 09:07 IST`. That's it. The
scheduler lives inside the container, so there's no cron to set up. It runs while the container runs,
restarts after a reboot, and stops when you run `docker compose down`.

Useful commands:

| What | Command |
|---|---|
| Update after a `git pull` | `docker compose up -d --build` |
| Apply `.env` or config changes | `docker compose up -d` (config only: `docker compose restart writer`) |
| Check your setup | `docker compose run --rm writer python cli.py validate <client>` |
| Send a test email | `docker compose run --rm writer python cli.py notify-test` |
| Write one article now | `docker compose run --rm writer python cli.py run <client>` |
| Stop | `docker compose down` |

Plans, drafts and history are kept in the `seo-data` volume, so rebuilding doesn't lose them.
`docker compose down -v` deletes them.

There's also a small web page for seeing the plan and writing an article on demand:
`docker compose --profile web up -d`. It shows the client named in `CLIENT` in `.env` and only
listens on localhost, so on a server open it through an SSH tunnel:
`ssh -L 8000:127.0.0.1:8000 you@server`, then visit http://127.0.0.1:8000.

### Without Docker

```bash
./venv/bin/python cli.py schedule on
```

This adds a daily job to launchd on macOS or cron on Linux, at `SCHEDULE_TIME` in `SCHEDULE_TZ`
(converted to the server's clock). `schedule status` and `schedule off` do what you'd expect.
Output goes to `data/auto.log`.

Run the schedule on one machine only, or you'll get every article twice.

## Settings in `.env`

| Variable | What it's for |
|---|---|
| `GEMINI_API_KEY`, `UNSPLASH_ACCESS_KEY` | Required |
| `PUBLISH_TO` | `strapi`, `wordpress` or `files` (overrides the config) |
| `STRAPI_API_TOKEN`, `WP_USERNAME`, `WP_APP_PASSWORD` | CMS access, used in the config as `${NAME}` |
| `POSTS_PER_MONTH`, `PUBLISH_DAYS` | How many articles and on which days, e.g. `8` and `tue,fri` |
| `SCHEDULE_TIME`, `SCHEDULE_TZ` | When the daily check runs, e.g. `09:07` and `Asia/Kolkata` |
| `RUN_ON_START` | `1` to also run once when it starts |
| `RESEND_API_KEY`, `NOTIFY_FROM`, `NOTIFY_TO` | Email updates |
| `CLIENT` | Which client the Docker web page shows |
| `GEMINI_MODELS` | Optional: which Gemini models to try, in order |

The schedule settings apply to every client. For different values per client, set `posts_per_month`
and `publish_weekdays` in each config instead.

**How posting days work:** the articles are spread evenly over the allowed days in the month. With
8 posts on Tuesdays and Fridays you get one roughly every 3 to 4 days. If the plan is made mid-month,
that month gets fewer. Changes take effect from the next month's plan.

## Email updates

Add your Resend key, a sender on a domain you've verified in Resend, and where to send it. Then run
`python cli.py notify-test`. You'll get one email for each run that actually does something:

- the month's plan, when it's made
- a new draft, with the editor's score and notes and a link to review it
- a published post, with its link
- a topic skipped because it's already on the site
- anything that failed (it retries the next day; after three tries the subject says **Action needed**)
- the job itself crashing

Quiet days send nothing.

## Commands

```bash
python cli.py list                         # all clients
python cli.py add-client <id>              # new client from the example config
python cli.py validate <client>            # check keys, CMS access and config
python cli.py run <client> [--dry-run] [--keyword "..."]   # one article now
python cli.py plan <client> [--new]        # show or remake this month's plan
python cli.py auto                         # the daily job, for every enabled client
python cli.py push <client> <name>         # upload a saved article
python cli.py serve <client>               # web page on http://127.0.0.1:8000
python cli.py schedule on|off|status       # daily job via launchd / cron
python cli.py daemon                       # built-in scheduler (what Docker runs)
python cli.py notify-test                  # test email
```

## About the free tier

Gemini's free tier gives roughly 20 requests a day per model, per Google Cloud project. An article
takes 4 to 10, so a couple of articles a week is comfortable. When a model is busy or out of quota it
moves on to the next one, and if they're all unavailable the article simply waits until the next day.
Creating more keys in the same project doesn't add quota.

## Tests

```bash
python -m unittest discover tests
```

They run offline and don't use any API quota.

## License

MIT. See [LICENSE](LICENSE).
