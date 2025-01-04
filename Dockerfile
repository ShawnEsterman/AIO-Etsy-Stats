FROM python:3.13-slim-bullseye

ENV PYTHONUNBUFFERED="1"
ENV PIP_ROOT_USER_ACTION="ignore"

COPY . /app

RUN pip3 install setuptools --upgrade && pip3 install /app/.

ENTRYPOINT [ "python3", "/app/aio_etsy_stats/main.py" ]