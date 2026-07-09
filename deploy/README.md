# Deploying to GCP (us-west1, beside the UAT Mongo)

The app is one Docker image (FastAPI serves the API **and** the built frontend).
This kit adds HTTPS (Caddy + Let's Encrypt) and nightly database backups.
Why us-west1: the outreach Mongo lives there — the app makes several DB queries per
page, so it must sit next to the database; Apollo/Gemini/Tavily/Clerk are US-hosted too.

## 1. Create the VM (once)
```bash
gcloud compute instances create outreach-app \
  --zone=us-west1-b --machine-type=e2-small \
  --image-family=debian-12 --image-project=debian-cloud \
  --tags=http-server,https-server
gcloud compute firewall-rules create allow-http-https \
  --allow tcp:80,tcp:443 --target-tags=http-server,https-server
```
~$15/month. Install Docker on it: `curl -fsSL https://get.docker.com | sh`

## 2. Get the code + secrets onto the VM
```bash
git clone https://github.com/rishav-wq/outreach_knowella.git /opt/outreach-agent
cd /opt/outreach-agent
# create .env by hand (it is gitignored) — copy values from your local .env:
#   MONGO_URI, MONGO_DB, APOLLO_API_KEY, GOOGLE_API_KEY, TAVILY_API_KEY,
#   CLERK_SECRET_KEY, CLERK_PUBLISHABLE_KEY, ALLOWED_EMAIL_DOMAINS
```

## 3. DNS + start
Point an A record (e.g. `outreach.knowella.com`) at the VM's external IP, then:
```bash
DOMAIN=outreach.knowella.com docker compose -f deploy/docker-compose.yml up -d --build
```
Caddy fetches the TLS certificate automatically. App is live at https://outreach.knowella.com

## 4. Clerk
Clerk dashboard → Domains → add `https://outreach.knowella.com`.
(For a real launch, switch to a production Clerk instance and its `pk_live_/sk_live_` keys.)

## 5. Backups (do not skip — the do-not-contact list lives in this DB)
```bash
chmod +x deploy/backup.sh
crontab -e   # add:
# 15 2 * * * /opt/outreach-agent/deploy/backup.sh >> /var/log/outreach-backup.log 2>&1
```
Restore: `docker run --rm -i mongo:6 mongorestore --uri "$MONGO_URI" --archive --gzip < backup.archive.gz`

## Redeploy after changes
```bash
cd /opt/outreach-agent && git pull && \
  DOMAIN=outreach.knowella.com docker compose -f deploy/docker-compose.yml up -d --build
```

## Notes
- The VM can also reach Mongo over its internal IP if both are in the same VPC —
  swap the host in MONGO_URI for lower latency and no public exposure.
- Frontend API base: production builds call same-origin (no VITE_API_BASE needed).
