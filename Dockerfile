FROM selenium/standalone-firefox:133.0

RUN apt install python3 python3-pip python3-venv

RUN python -m venv /app \
    && source /app/bin/activate \
    && pip install setuptools --upgrade --quiet \
    && pip install /app/. --quiet \
    && python /app/aio_etsy_stats/main.py"