FROM selenium/standalone-firefox:133.0

USER root

RUN apt-get -y update && apt-get install -y python3 python3-pip python3-venv python3-setuptools

COPY --chown=1200:1201 . /app

USER 1200

RUN python3 -m venv /app \
    && . /app/bin/activate \
    && pip3 install /app/. --quiet

CMD [ "echo $UID", "&&", "/bin/bash", "-c", "/app/bin/activate", "&&",  "python3", "/app/aio_etsy_stats/main.py" ]