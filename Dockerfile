FROM selenium/standalone-firefox:133.0

USER root

RUN apt-get -y update && apt-get install -y python3 python3-pip python3-venv

COPY --chown=1200:1201 . /app

USER 1200

RUN python -m venv /app \
    && source /app/bin/activate \
    && pip install setuptools --upgrade --quiet \
    && pip install /app/. --quiet \
    && python /app/aio_etsy_stats/main.py