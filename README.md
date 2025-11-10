# RateMyPDF
RateMyPDF is a website that helps paper form authors (particularly for court forms) improve the usability of their forms for self-represented litigants. It uses the FormFyxer library to deliver its insights.

The [first version](https://github.com/SuffolkLITLab/docassemble-PDFStats) of this website ran on Flask. This repository replaces it with a version on FastAPI.

It has been described in a paper published in the proceedings
of ICAIL '23. You can view it [here](https://suffolklitlab.org/docassemble-AssemblyLine-documentation/docs/complexity/complexity/#download-and-cite-our-paper).

## Running locally

Install requirements:

- formfyxer
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
TOOLS_TOKEN=
IN_DOCKER=TRUE
REDIS_URL=redis://ratemypdf_redis:6379
```

Fill in the missing values with the appropriate domain name, key, etc.

Access to the spot and tools tokens is available only by contacting suffolklitlab@gmail.com

## Preferred citation format

Please cite this repository as follows:

Quinten Steenhuis, Bryce Willey, and David Colarusso. 2023. Beyond Readability with RateMyPDF: A Combined Rule-based and Machine Learning Approach to Improving Court Forms. In _Proceedings of International Conference on Artificial Intelligence and Law (ICAIL 2023). ACM, New York, NY, USA, 10 pages_. https://doi.org/10.1145/3594536.3595146

Bibtex format:
```bibtex
@article{Steenhuis_Willey_Colarusso_2023, title={Beyond Readability with RateMyPDF: A Combined Rule-based and Machine Learning Approach to Improving Court Forms}, DOI={https://doi.org/10.1145/3594536.3595146}, journal={Proceedings of International Conference on Artificial Intelligence and Law (ICAIL 2023)}, author={Steenhuis, Quinten and Willey, Bryce and Colarusso, David}, year={2023}, pages={287–296}}
```
