# Handoff log

## 2026-09-18 — Switch hCaptcha to Cloudflare Turnstile

**State:**
- Code migration: **done**, merged to `main`.
- Light theme for the widget: **done**, merged to `main`.
- Production siteverify issue: **in-progress / blocked on user investigation** — Cloudflare dashboard reported "siteverify isn't being called for openpathtutoring" even though the user confirmed the new code is deployed and `TURNSTILE_SITE_KEY`/`TURNSTILE_SECRET_KEY` are set in production. Root cause not yet identified.

**What I did & why:**
- Replaced the unmaintained `Flask-hCaptcha` dependency with a small first-party `Turnstile` class ([app/turnstile.py](../../app/turnstile.py)) that mirrors its interface (`get_code()`/`verify()`/`init_app()` + `turnstile`/`turnstile_with()` template globals). Chose this over adding a new third-party package because Turnstile's server contract (site key, secret key, POST token to a siteverify URL) is nearly identical to hCaptcha's, so a thin first-party wrapper kept `app/utils.py`'s session-grace-period logic (`show_turnstile`/`check_turnstile_or_session`) untouched — only renames were needed at call sites.
- Renamed `HCAPTCHA_SITE_KEY`/`HCAPTCHA_SECRET_KEY` → `TURNSTILE_SITE_KEY`/`TURNSTILE_SECRET_KEY` everywhere (config, routes, local `.env`). **`.env` is gitignored** — production's own env config had to be updated separately by the user (confirmed done).
- Dropped a dead `hcaptcha_key` variable in `main_routes.py` that was passed to several `render_template()` calls but never referenced by any template.
- `TestingConfig` now uses Cloudflare's documented always-pass dummy keys (`1x00000000000000000000AA` / `1x0000000000000000000000000000000AA`) so tests don't need network mocking.
- Set the widget theme to `light` (Cloudflare notice / user request) by passing `theme='light'` through both `init_app()`'s kwargs (covers the default `{{ turnstile }}` widget) and the explicit `turnstile_with(callback='captcha2Passed', ...)` override in `signin.html` (explicit kwargs replace, not merge with, the init_app defaults — see `Turnstile.get_code()`).
- Diagnosed the "siteverify isn't being called" notice: `verify()` was independently confirmed to make a real, successful POST to Cloudflare's siteverify endpoint (tested locally against the real endpoint with the always-pass dummy key). With code deployed and prod env vars confirmed correct, the remaining likely causes are a **domain mismatch** in the Cloudflare Turnstile dashboard's widget settings, or something in front of the app (reverse proxy CSP) blocking `challenges.cloudflare.com`'s script — neither of which I can inspect from this repo/session.

**Artifacts:**
- commit `5c8494d` — core hCaptcha → Turnstile migration (extension, config, routes, 12 templates, `disable-submit.js`, `requirements.txt`)
- commit `9cb680a` — merge of the migration branch to `main`
- commit `8cb2436` / `6912b80` — light theme change + merge
- [app/turnstile.py](../../app/turnstile.py) — the new extension
- [app/utils.py](../../app/utils.py) — `show_turnstile`, `check_turnstile_or_session`
- [app/extensions.py](../../app/extensions.py) — `turnstile.init_app(app, callback='captchaPassed', theme='light')`
- [app/static/js/disable-submit.js](../../app/static/js/disable-submit.js) — `.cf-turnstile[data-callback=...]` gates form submit

**Open questions / blockers:**
- Is the Turnstile widget's Cloudflare dashboard "Domains" list set to the exact production hostname (e.g. bare domain vs `www.`)?
- Does the production reverse proxy set a CSP header that would block `challenges.cloudflare.com` script/frame origins? (Nothing in this Flask app sets CSP itself.)
- Has the user checked the widget in production DevTools for an inline Turnstile error code (e.g. `Error: 110200`) or confirmed via view-source that the real site key (`0x4AAAAAAExn7mp7Va_LaMc4...`, not a dummy) is actually rendered?

**Next step:** Wait for the user to report back what they see in production DevTools (Network tab load of `api.js`, any inline widget error code, Console CSP violations) and the Cloudflare dashboard's Domains list for the widget — then diagnose from there. See [Cloudflare's Turnstile client-side error codes](https://developers.cloudflare.com/turnstile/troubleshooting/client-side-errors/error-codes/) as the fastest lookup once an error code is known.
