FROM selenium/standalone-firefox:133.0

ENV PYTHONUNBUFFERED="1"
ENV PIP_ROOT_USER_ACTION="ignore"

USER root

RUN apt-get -y update && apt-get install -y python3-full python3 python3-pip python3-venv python3-setuptools

COPY --chown=1200:1201 . /app

USER 1200

RUN pip3 install /app/. --quiet --break-system-packages

CMD [ "/bin/bash", "-c", "python3", "/app/aio_etsy_stats/main.py" ]