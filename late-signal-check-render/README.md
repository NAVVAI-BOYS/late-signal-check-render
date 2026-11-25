# The Late Signal Check (Rainmaker)

Put every file in this folder at the ROOT of your GitHub repo, not inside a subfolder. render.yaml is only read from the repo root.

## Render settings (manual Web Service)

| Setting | Value |
|---|---|
| Runtime | Python 3 |
| Build command | `pip install -r requirements.txt` |
| Start command | `gunicorn app:app --workers 2 --bind 0.0.0.0:$PORT` |
| Health check path | `/healthz` |

Or deploy as a Blueprint and Render reads render.yaml for you.

## Environment variables

| Key | Needed | What it does |
|---|---|---|
| ADMIN_KEY | Yes | Password for the leads sheet |
| DATA_DIR | Optional | Where leads are saved. Default /var/data |
| RESEND_API_KEY | Optional | Turns on an email for every new lead |
| NOTIFY_TO | Optional | Who gets the lead email (comma separated) |
| NOTIFY_FROM | Optional | Sender, for example `Leads <leads@yourdomain.com>` |

## Saving leads

- Starter plan: add a 1 GB disk mounted at /var/data (render.yaml does this). Leads survive redeploys.
- Free plan: no disks. The app still runs and saves leads, but a redeploy wipes them. Turn on the email so you keep a copy.

## Links once live

- App: `https://YOUR-APP.onrender.com/`
- Leads sheet: `https://YOUR-APP.onrender.com/admin/sheet?key=YOUR_ADMIN_KEY`
- CSV: `https://YOUR-APP.onrender.com/admin/leads.csv?key=YOUR_ADMIN_KEY`
- Health: `https://YOUR-APP.onrender.com/healthz`
