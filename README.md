# RateMyPDF
RateMyPDF is a website that helps paper form authors (particularly for court forms) improve the usability of their forms for self-represented litigants. It uses the FormFyxer library to deliver its insights.

The [first version](https://github.com/SuffolkLITLab/docassemble-PDFStats) of this website ran on Flask. This repository replaces it with a version on FastAPI.

## Running locally

Install requirements:

- FormFyxer. You will need the version from GitHub. git+https://github.com/SuffolkLITLab/FormFyxer.git
- redis. Follow install install instructions here: https://redis.io/docs/getting-started/installation/install-redis-on-linux/
- rq: pip install rq


Start redis queue to handle incoming jobs

```bash
cd ~/RateMyPDF/app
rq worker
```

Start the fastapi app, setting the redis URL to `localhost`

```bash
cd ~/RateMyPDF/app
REDIS_URL=redis://localhost:6379 python main.py
```

The site should now be available at http://localhost:8000

## Starting in Docker

Copy the `.env.example` file to `.env`

```yaml
DOMAIN=ratemypdf.com
OPEN_AI__org=org-
OPEN_AI__key=sk-
SPOT_TOKEN=
SECRET_KEY=
TOOLS_TOKEN=
IN_DOCKER=TRUE
REDIS_URL=redis://ratemypdf_redis:6379
```

Fill in the missing values with the appropriate domain name, key, etc.

Access to the spot and tools tokens is available only by contacting suffolklitlab@gmail.com