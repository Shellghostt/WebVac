# Authentication Architecture

**Parent:** [Full System Architecture](../ARCHITECTURE.md)  
**Code root:** `webvac/auth/` · wiring in `webvac/cli/scraper.py`, `webvac/core/crawler.py`, `webvac/core/page_scrape_flow.py`, `webvac/utils/browser.py`

---

## 1. Goals

- Log in once with Patchright, persist session, reuse across crawl slots.
- Survive mid-crawl session loss (auth walls) with a safe default policy (`skip`).
- Support MFA/TOTP, multi-step forms, OAuth manual bootstrap, and optional encrypted sessions.

---

## 2. Component diagram

```mermaid
flowchart TB
  subgraph entry [Entry]
    Scraper[webvac/cli/scraper.py]
    RunPy[run.py]
  end

  subgraph facade [Facade]
    Mgr[AuthManager]
    Profile[AuthProfile]
  end

  subgraph engines [Engines]
    PR[AuthHandler Patchright]
  end

  subgraph support [Support]
    Steps[steps.py]
    MFA[mfa.py]
    Pop[popups.py]
    Wall[wall.py]
    Sess[session_store.py]
    Creds[credentials.py]
    Audit[cookie_audit.py]
  end

  subgraph browser [Browser]
    BM[BrowserManager]
  end

  subgraph crawl [Crawl]
    Flow[page_scrape_flow]
    Crawler[crawler]
  end

  RunPy --> Scraper
  Scraper --> Mgr
  Mgr --> Profile
  Mgr --> PR
  Mgr --> Steps
  Mgr --> MFA
  Mgr --> Pop
  Mgr --> Wall
  Mgr --> Sess
  Mgr --> Creds
  Mgr --> Audit
  Mgr --> BM
  Flow --> Wall
  Flow -->|relogin| Mgr
  Crawler --> Wall
  BM -->|broadcast state| Crawler
```

---

## 3. Auth lifecycle

```mermaid
stateDiagram-v2
  [*] --> Idle
  Idle --> Bootstrap: --auth-bootstrap
  Idle --> Restore: session file exists
  Idle --> Login: --login + credentials

  Bootstrap --> Authenticated: Enter after manual SSO
  Restore --> Verify: auth-check-url set
  Restore --> Authenticated: verify OK / no check
  Restore --> Login: expired or verify fail

  Login --> StepsOrEngine: profile steps or classic fill
  StepsOrEngine --> MFA: OTP / TOTP / CAPTCHA
  MFA --> Persist: capture storage_state
  Persist --> Verify
  Verify --> Authenticated: OK
  Verify --> Failed: wall still present

  Authenticated --> Crawl
  Crawl --> AuthWall: mid-crawl wall detected
  AuthWall --> Skip: policy skip
  AuthWall --> Abort: policy abort
  AuthWall --> Login: policy relogin
  Authenticated --> [*]
  Failed --> [*]
```

---

## 4. Module responsibilities

| Module | Responsibility |
|--------|----------------|
| `manager.py` | Single facade: restore, login, verify, bootstrap, ensure, is_auth_wall |
| `profile.py` | Rich JSON profile: selectors, steps, totp, policies, TTL |
| `session_store.py` | `storage_state` I/O, TTL meta, optional Fernet |
| `credentials.py` | `WEBVAC_USER` / `WEBVAC_PASS`, redact helpers |
| `auth.py` | Patchright classic login (auto + manual selectors) |
| `steps.py` | Declarative multi-step runner |
| `mfa.py` | TOTP generation + interactive OTP/CAPTCHA pause |
| `wall.py` | Heuristics for login pages + logout URL deny |
| `popups.py` | Cookie/consent banner dismiss |
| `cookie_audit.py` | Flag warnings after login; VAPT reuse |
| `default_creds.py` | Vendor default-panel fingerprints |

---

## 5. Session & storage_state flow

```mermaid
sequenceDiagram
  participant AM as AuthManager
  participant Eng as Patchright
  participant BM as BrowserManager
  participant SS as session_store
  participant Disk as sessions/*.json

  AM->>Eng: login on Patchright slot 0
  Eng-->>AM: success
  AM->>BM: capture_auth_session(slot=0)
  AM->>BM: broadcast_auth_session all slots
  AM->>SS: save_session storage_state + meta
  SS->>Disk: write plaintext or Fernet blob

  Note over AM,Disk: Later run
  AM->>SS: load_session
  SS->>Disk: read
  alt TTL expired
    AM-->>AM: force re-login
  else valid
    AM->>BM: set_auth_session + broadcast
    opt auth-check-url
      AM->>BM: goto check URL
      AM->>AM: is_auth_wall?
    end
  end
```

**Formats accepted:**

1. Playwright `storage_state` (`cookies` + `origins`) — preferred  
2. Legacy plain cookie list JSON — normalized on load  

**Metadata (`_webvac_session_meta`):** `created_at`, `last_verified_at`, `ttl_sec`, `seed_url`

---

## 6. Mid-crawl auth-wall policy

```mermaid
flowchart TD
  Goto[page.goto success] --> Check{authenticated?}
  Check -->|no| Continue[continue scrape]
  Check -->|yes| Wall{is_auth_wall?}
  Wall -->|no| Continue
  Wall -->|yes| Policy{on_auth_wall}
  Policy -->|skip| Skip[close page, skip URL]
  Policy -->|abort| Abort[raise / stop crawl]
  Policy -->|relogin| Relogin[AuthManager.login]
  Relogin -->|ok| Retry[retry URL]
  Relogin -->|fail| Skip
```

Heuristics (`wall.py`): password inputs, login path keywords, sign-in titles, seed login path match.

Logout soft-deny when authed: `/logout`, `/signout`, `/sign-out`, `/log-out`.

---

## 7. Credential & secret surfaces

```mermaid
flowchart LR
  CLI["--username --password"] --> Resolve[resolve_credentials]
  Env["WEBVAC_USER WEBVAC_PASS"] --> Resolve
  JSON["auth profile JSON"] --> Resolve
  Resolve --> Mgr[AuthManager.login]
  Key["WEBVAC_SESSION_KEY"] --> Fernet[session_store encrypt]
  Fernet --> Disk[session file]
```

- Passwords redacted in `run.py` printed commands.
- Real `auth_creds.json` is gitignored; ship `examples/auth_creds.example.json` only.
- Profiles with `auth_engine: "nodriver"` are rejected (Nodriver was removed).

---

## 8. Login modes

| Mode | Login | Crawl |
|------|-------|-------|
| Default `--login` | Patchright (`AuthHandler`) | Patchright |
| `--auth-bootstrap` | Visible Patchright manual SSO | Patchright |
| `--session-file` only | Restore cookies (skip login) | Patchright |

Login always on **slot 0**. `--login` forces `--engine dynamic` (no lightweight).

---

## 9. CLI / env surface

```
--login
--login-url
--username / --password
--session-file
--auth-profile
--auth-check-url
--on-auth-wall abort|skip|relogin
--session-ttl
--auth-bootstrap
--otp-prompt
--no-auth-proxy-rotate
--dismiss-selector (repeatable)
```

Env: `WEBVAC_USER`, `WEBVAC_PASS`, `WEBVAC_SESSION_KEY`
