# Security, secrets & responsible use

**Parent:** [OVERVIEW](OVERVIEW.md)

---

## 1. Intended use

WebVac is a powerful browser automation and crawl tool. Use it only against systems you are **authorized** to test or scrape. Unauthorized access, credential stuffing, or CDN/origin bypass without permission may be illegal.

---

## 2. Secrets that must stay local

| Path / env | Purpose | In git? |
|------------|---------|---------|
| `auth_creds.json` | Login credentials / profiles | **No** (gitignored) |
| `proxies.txt` | Proxy endpoints + creds | **No** |
| `capsolver.key` / `.env` | CapSolver API key | **No** |
| `sessions/` | storage_state cookies | **No** |
| `CAPSOLVER_API_KEY`, `WEBVAC_CAPSOLVER_KEY`, `WEBVAC_USER`, `WEBVAC_PASS`, `WEBVAC_SESSION_KEY` | Env secrets | **No** |

Templates live under `examples/` (`*.example.*`). Copy and rename locally.

**Never** pass long-lived API keys on the CLI in shared shell history if you can use `capsolver.key` instead.

---

## 3. Session encryption

Set `WEBVAC_SESSION_KEY` to enable Fernet encryption for saved `storage_state` files. Without it, session files are plaintext JSON on disk.

---

## 4. Auth vs bot ethics

- Auth-wall pages are skipped by default — they are not “beaten” as WAF challenges.
- CapSolver spends money and interacts with third-party solver infrastructure; only enable keys you control.
- Managed Cloudflare interstitials often cannot be solved by CapSolver; do not assume auto-bypass.

---

## 5. Proxies & IP exposure

If `proxies.txt` entries fail health-check, WebVac continues on your **real IP** and prints a warning. That is intentional availability behavior — treat it as an operational risk on sensitive targets.

Residential playbooks pin UA/geo for consistency; ensure your provider ToS allows automation.

---

## 6. Origin IP bypass

Origin probing (Host header + IP fetch / Chromium MAP) is for **authorized** CDN-edge bypass scenarios only. It is not advertised as a casual CLI feature. Misuse can violate laws and vendor terms.

---

## 7. robots.txt

Default is **bypass** (`--no-robots`). Use `--respect-robots` when policy requires obedience. Bypassing robots does not grant legal permission.

---

## 8. Logging & redaction

Credential helpers redact passwords in logs where implemented. Still avoid printing full `auth_creds.json` or CapSolver keys into tickets/chat.

Network debug dumps may include request URLs and truncated bodies — treat `network/*.json` as sensitive.

---

## 9. Dependency surface

- Patchright / Chromium — full browser attack surface
- CapSolver cloud API — third-party processing of sitekeys / page URLs
- De-Caffeinator submodule — separate Node toolchain; keep submodule updated deliberately

---

## 10. Related

- [AUTH](architecture/AUTH.md)  
- [CAPTCHA](architecture/CAPTCHA.md)  
- [PROXY_ORIGIN](architecture/PROXY_ORIGIN.md)  
- [CONFIG_REFERENCE](CONFIG_REFERENCE.md)  
