# SEO Content Agent — Product Plan

> Turning the NaviGo blog automation into a sellable, multi-tenant client product.

## 1. What it is

**SEO Content Agent** is a done-for-you autopilot that:

1. **Discovers** trending keywords/topics for each client's niche (Google Trends, Google News, AI-company RSS, YouTube creator feeds, marketing blogs).
2. **Researches** the chosen topic from live web sources.
3. **Drafts** a full, SEO-structured blog post in the client's brand voice and template (hero, key takeaways, TOC, sections, comparison table, FAQ, CTA).
4. **Generates branded images** (featured + inline infographics) via Gemini Imagen, with the client's logo overlaid.
5. **Auto-publishes** to the client's WordPress with Rank Math/Yoast SEO meta, categories, tags.
6. **Injects schema** (Article + FAQPage + HowTo JSON-LD).
7. **Indexes** the URL (Google Indexing API, IndexNow/Bing/Yandex, optional GSC browser submit).
8. **Logs** every post for reporting.

It is the NaviGo pipeline, generalized so **every brand-specific value is per-client config** instead of hardcoded.

## 2. From single-tenant to product — the core change

The existing `ai-wordpress-agent/main.py` is excellent but single-tenant: NaviGo's name, palette, internal links, WP URL, phone, audience, and topic sources are baked into constants. **Productizing = extracting all of that into a `ClientConfig`** and running the same proven pipeline per tenant.

| Hardcoded today | Becomes per-client config |
|---|---|
| `WP_SITE_URL`, `WP_USERNAME`, `WP_APP_PASSWORD` | `client.wordpress.*` |
| `INTERNAL_LINKS`, sitemap URL | `client.internal_links`, `client.sitemap_url` |
| `HTML_STYLE` colors | `client.brand.palette`, `client.brand.fonts` |
| `WHATSAPP_CTA`, `WP_PHONE` | `client.cta.*` |
| Brand name / location / audience in prompts | `client.brand.*`, `client.audience` |
| Topic-source RSS/YouTube/Trends lists, geo | `client.sources.*`, `client.geo` |
| Category enum | `client.categories` |
| `logo.png` | `clients/<id>/assets/logo.png` |

Production `ai-wordpress-agent/` is left **untouched** (it's a live cron job — see its CLAUDE.md). NaviGo is re-onboarded as **tenant #1** in the new engine so we can run it the new way once validated, side by side.

## 3. Architecture

```
seo-content-agent/
  agent/                  # the reusable, config-driven engine
    config.py             # ClientConfig dataclass + YAML loader + validation
    ai.py                 # DeepSeek-primary / Claude-fallback wrapper
    trends.py             # topic discovery (Trends/News/RSS/YouTube), de-dupe
    research.py           # live web research for a topic
    writer.py             # blog generation (brand template, internal links)
    images.py             # Gemini featured + inline images, logo overlay
    publisher.py          # WordPress REST publish + categories/tags + schema
    indexer.py            # Google Indexing API + IndexNow + cache flush
    state.py              # per-client used-topics / posted-headlines store
    pipeline.py           # run_once(client) — orchestrates all steps
    runner.py             # loop over enabled clients; scheduling hooks
  clients/
    _template/config.yaml # copy-to-onboard schema with every field documented
    navigo/config.yaml    # NaviGo as tenant #1
    navigo/assets/logo.png
  data/<client_id>/       # runtime state: used_topics, headlines, logs, queue
  cli.py                  # run | run-all | add-client | list | validate
  dashboard/app.py        # (Phase 2) Flask client portal: posts, approvals
  .env.example            # shared infra secrets (AI keys, optional infra)
  requirements.txt
  README.md
```

**Secrets split:** *platform* secrets (DeepSeek, Anthropic, Gemini, Pexels keys) live in `.env` / host env once. *Client* secrets (WP app password) live in that client's config (or env-interpolated `${VAR}` for security). This keeps one AI bill at the agency and isolates client WP creds.

## 4. Multi-tenancy & isolation

- Each client = one folder under `clients/` + one runtime folder under `data/`.
- State (used topics, posted headlines, retry queue) is namespaced per client → no cross-bleed of dedupe history.
- A run for client A never imports client B's config; the pipeline takes a single `ClientConfig`.
- Per-client `enabled`, `posts_per_day`, `schedule`, and `topic_mode` (`trending` | `breaking` | `evergreen_queue`).

## 5. Onboarding a new client (the sales-to-live flow)

1. `python cli.py add-client acme` → scaffolds `clients/acme/config.yaml` from `_template`.
2. Fill in: WP URL + application password, brand name/voice, palette/fonts, audience, geo, niche topic sources, CTA, logo.
3. `python cli.py validate acme` → checks WP auth, sitemap reachability, required keys.
4. `python cli.py run acme --dry-run` → generates a post to HTML on disk for client approval (no publish).
5. Flip `enabled: true`, set schedule → `runner` picks it up.

Target: **a new client live in under 30 minutes**, no code changes.

## 6. Packaging & pricing (suggested)

| Tier | Posts/mo | Images | Indexing | Approval flow | Price (₹/mo) |
|---|---|---|---|---|---|
| Starter | 8 | Stock (Pexels) | IndexNow | Auto-publish | 7,999 |
| Growth | 16 | AI branded | + Google Indexing API | Optional review | 14,999 |
| Authority | 30 + breaking | AI branded + inline | + GSC submit | Review + monthly report | 29,999 |

Add-ons: custom template design, GSC/GA reporting dashboard, multi-language, social repurposing. Margin driver: AI cost per post is a few cents (DeepSeek primary), so gross margin is very high; the moat is the brand-template + indexing + reliability, not the raw generation.

## 7. Roadmap

- **Phase 1 (this build):** config-driven engine, NaviGo tenant, CLI run/onboard/validate, dry-run-to-HTML, per-client state. ✅ functional.
- **Phase 2:** Flask client portal (login, see posts, approve/reject queued topics, download monthly report), webhook on publish.
- **Phase 3:** GSC + GA4 read-back per client → "ranking & traffic" report; topic suggestions from actual Search Console queries.
- **Phase 4:** Shopify/Webflow/Ghost publishers (not just WordPress); social repurposing (LinkedIn/X threads from each post); white-label reseller mode.

## 8. Risks & mitigations

- **WP credential security** → support `${ENV_VAR}` interpolation; never log secrets; recommend least-privilege app passwords.
- **AI hallucination on facts** → research step grounds the draft; keep the dry-run approval gate for new clients.
- **Duplicate/low-quality at scale** → per-client dedupe + min-word-count + template validation before publish.
- **Indexing quota** → retry queue (already designed), IndexNow as the always-on fallback.
- **Provider outages** → DeepSeek→Claude fallback already in the AI layer; image step is non-fatal.
