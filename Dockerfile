FROM selenium/standalone-chrome:4.27

ENV PYTHONUNBUFFERED="1"
ENV PIP_ROOT_USER_ACTION="ignore"

USER root

RUN apt-get -y update \
    && apt-get install -y python3 python3-pip python3-setuptools

COPY --chown=1200:1201 . /app

RUN pip3 install /app/. --quiet --break-system-packages

USER 1200:1201

ENTRYPOINT [ "python3", "/app/aio_etsy_stats/main.py" ]