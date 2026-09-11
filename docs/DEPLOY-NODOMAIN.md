# Deploy qrtr for ₹0 — no domain required

**The one thing GitHub can't do is run this app** (Pages = static files only; Codespaces = ~60 free
hours/month). So this is the ₹0 architecture:

| Piece | Provider | Cost |
|---|---|---|
| Code + CI/CD + Docker images (GHCR) | GitHub (already done — see `.github/workflows/`) | ₹0 |
| Landing page (`landing/`) | GitHub Pages → `nangti.github.io/qrtr` | ₹0 |
| **The app itself** | **Oracle Cloud Always Free VM** — 4× ARM CPU, 24 GB RAM | ₹0 forever |
| **HTTPS name** (no domain purchase) | **DuckDNS** → `qrtr-YOU.duckdns.org` | ₹0 |
| TLS certificates | Caddy + Let's Encrypt (automatic) | ₹0 |
| Backups | Backblaze B2 (10 GB free) + Litestream | ₹0 |

> ⚠️ **Do not print QR codes until this is live and the final URL is confirmed.** Printed QRs embed
> the URL permanently — that's the whole point of the dynamic redirect layer, but the *short* URL
> itself must be stable from day one.

---

## Path A (recommended, ~45 min): Oracle free VM + DuckDNS

### 1. Create the VM
1. Sign up at [cloud.oracle.com/free](https://cloud.oracle.com/free) (identity check only; the "Always Free" tier is never billed).
2. Create a Compute instance: **Ampere A1 (ARM)**, any shape up to 4 OCPU/24 GB, Ubuntu 24.04, save the SSH private key.
3. **Open the firewall — two places (everyone trips here):**
   - OCI Console → instance → Subnet → Security List → add ingress rules: TCP 80 and TCP 443 from `0.0.0.0/0`.
   - On the VM itself (Ubuntu images also ship an iptables wall):
     ```bash
     sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
     sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
     sudo netfilter-persistent save
     ```
4. Install Docker: `curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER` → log out/in.

> No capacity / don't want Oracle? Alternative free hosts that work with this guide: a spare laptop
> at home with [Tailscale Funnel](https://tailscale.com/kb/1223/funnel) (free HTTPS `*.ts.net`),
> or [Fly.io](https://fly.io) free allowance (`qrtr.fly.dev`). Anything that runs Docker works.

### 2. Claim your free name
1. [duckdns.org](https://www.duckdns.org) → sign in (GitHub/Google) → create e.g. `qrtr-YOU` → point it at the VM's **public IP**.
2. You now own `qrtr-YOU.duckdns.org` forever, free. Let's Encrypt issues certs for it normally.

### 3. Deploy
```bash
# on the VM
git clone https://github.com/nangti/qrtr.git ~/qrtr && cd ~/qrtr
cat > .env <<EOF
DOMAIN=qrtr-YOU.duckdns.org
APP_DOMAIN=qrtr-YOU.duckdns.org
BASE_URL=https://qrtr-YOU.duckdns.org
# Signup is invite-only by default: the FIRST account you create becomes the
# owner/admin, after which signup closes and you invite users from /admin.
# Set ALLOW_SIGNUP=1 only when you launch publicly.
EOF
docker compose -f deploy/docker-compose.prod.yml --env-file .env up -d
```
Wait ~60 s for TLS issuance, then open `https://qrtr-YOU.duckdns.org` → sign up → create a QR →
scan it with your phone. ✅

> **If `docker compose … pull` says "unauthorized":** the GHCR package starts out private.
> One-time fix — github.com/nangti → **Packages → qrtr → Package settings → Change visibility →
> Public** (the image already carries the `org.opencontainers.image.source` label, so it appears
> right on the repo's Packages section). ✅

### 4. Wire auto-deploy (optional, 5 min)
GitHub repo → Settings → Secrets and variables → Actions → add:
- `VPS_HOST` = VM public IP · `VPS_USER` = `ubuntu` · `VPS_SSH_KEY` = a **fresh** keypair's private key
  (`ssh-keygen -f qrtr-deploy`; append `qrtr-deploy.pub` to the VM's `~/.ssh/authorized_keys`).
Then Actions → **deploy** → Run workflow, or uncomment the `push: main` trigger in
`.github/workflows/deploy.yml` for fully automatic deploys.

### 5. Backups + uptime (₹0)
- [backblaze.com](https://www.backblaze.com) → B2 → 10 GB free bucket → uncomment the `litestream`
  service in `deploy/docker-compose.prod.yml` and add `deploy/litestream.yml` (sample in the
  container logs of litestream docs; 5 lines).
- [uptimerobot.com](https://uptimerobot.com) free → monitor `https://qrtr-YOU.duckdns.org/healthz`
  every 5 min → alerts to email/Telegram.

## Path B (5-minute demo): PythonAnywhere free

For showing people, not for printed QRs: [pythonanywhere.com](https://www.pythonanywhere.com) free
account → `git clone` the repo in a console → `mkvirtualenv qrtr -p python3.12 && pip install -r
requirements.txt` → Web tab → "manual config" WSGI:

```python
import sys, os
sys.path.insert(0, os.path.expanduser("~/qrtr"))
os.environ["DATA_DIR"] = os.path.expanduser("~/qrtr/data")
os.environ["COOKIE_SECURE"] = "1"   # pythonanywhere serves https
from run import app as application
```

Your app is at `YOU.pythonanywhere.com`. Free tier: clickable renewal every 3 months, daily CPU
quota, outbound network is allowlist-only (so **geo DB auto-download may fail** — stats then show
country "Unknown"; fine for a demo).

---

## When to spend the first rupee

| Trigger | Purchase | Cost |
|---|---|---|
| Printing QRs for customers (branding + trust) | A real domain — `qrtr.in` etc. | ~₹700–1,000/yr |
| >100k scans/day or customers paying | Hetzner CX22 instead of Oracle | €3.79/mo |
| Billing goes live | Razorpay (per-transaction, no fixed cost) | ~2%/txn |

Everything else in this stack stays ₹0 until then.
