FROM selenium/standalone-firefox:133.0

USER root

RUN apt-get -y update && apt-get install -y python3 python3-pip python3-venv python3-setuptools

COPY --chown=1200:1201 . /app

USER 1200

RUN pip3 install /app/. --quiet

CMD [ "python3", "/app/aio_etsy_stats/main.py" ]