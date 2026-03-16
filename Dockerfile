FROM python:3.12-slim

ENV APP_DIR=/usr/src/snappass

RUN groupadd -r snappass && \
    useradd -r -g snappass snappass && \
    mkdir -p $APP_DIR

WORKDIR $APP_DIR

COPY ["pyproject.toml", "requirements.txt", "README.rst", "AUTHORS.rst", "$APP_DIR/"]
COPY ["./snappass", "$APP_DIR/snappass"]

RUN pip install -r requirements.txt

RUN pybabel compile -d snappass/translations

RUN pip install . && \
    chown -R snappass $APP_DIR && \
    chgrp -R snappass $APP_DIR

USER snappass

# Default Flask port
EXPOSE 5000

# Use Gunicorn WSGI server instead of Flask development server
CMD ["sh", "-c", "gunicorn --workers=${GUNICORN_WORKERS:-3} --bind=0.0.0.0:${PORT:-5000} --access-logfile=- --error-logfile=- snappass.main:app"]
