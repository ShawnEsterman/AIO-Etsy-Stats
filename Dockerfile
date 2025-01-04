FROM python:3.13-slim-bullseye

ENV PYTHONUNBUFFERED="1"
ENV PIP_ROOT_USER_ACTION="ignore"

COPY . /app

RUN python3 -m venv /app \
    && source /app/bin/activate \
    && pip3 intsall setuptools --upgrade \
    && pip3 install /app/.

ENTRYPOINT [ "source", "/app/bin/activate" ]
CMD [ "python3", "/app/aio_etsy_stats/main.py" ]