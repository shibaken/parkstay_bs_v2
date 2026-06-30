# Prepare the base environment.
FROM ubuntu:26.04 AS builder_base_parkstay
################# Use the following base image for actual builds.
# FROM ghcr.io/dbca-wa/docker-apps-dev:ubuntu_2604_base_python_node AS builder_base_parkstay

MAINTAINER asi@dbca.wa.gov.au
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Australia/Perth
ENV PRODUCTION_EMAIL=True
ENV SECRET_KEY="ThisisNotRealKey"

############################
ENV NODE_MAJOR=24
# 1. Install base packages found in the official base image
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget git libmagic-dev gcc g++ make binutils gnupg \
    libproj-dev gdal-bin python3 python3-setuptools python3-dev python3-pip \
    tzdata rsyslog gunicorn virtualenv libpq-dev patch \
    postgresql-client mtr htop vim sudo build-essential \
    && apt-get clean

# 2. Setup environment structures (Mimicking base image)
# Essential for SSL and Python command compatibility
RUN update-ca-certificates && \
    ln -s /usr/bin/python3 /usr/bin/python

# 3. Install Node.js from NodeSource (Logic ported from base image)
RUN mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" \
    | tee /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y nodejs
############################

RUN apt-get clean
RUN apt-get update
RUN apt-get upgrade -y
RUN apt-get install --no-install-recommends -y run-one 
# RUN apt-get install --no-install-recommends -y wget git libmagic-dev gcc binutils libproj-dev gdal-bin python3 python3-setuptools python3-dev python3-pip tzdata libreoffice cron rsyslog 
# RUN apt-get install --no-install-recommends -y libpq-dev patch virtualenv
# RUN apt-get install --no-install-recommends -y mtr
# RUN apt-get install --no-install-recommends -y sqlite3 vim ssh htop
# RUN apt-get install --no-install-recommends -y postgresql-client
# RUN apt-get install --no-install-recommends -y nodejs npm
# RUN apt-get install --no-install-recommends -y python3-pil
RUN apt-get install --no-install-recommends -y python3-venv

RUN groupadd -g 5000 oim 
RUN useradd -g 5000 -u 5000 oim -s /bin/bash -d /app
RUN mkdir /app 
RUN chown -R oim.oim /app 

COPY timezone /etc/timezone
ENV TZ=Australia/Perth
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# # Default Scripts
# RUN wget https://raw.githubusercontent.com/dbca-wa/wagov_utils/main/wagov_utils/bin/default_script_installer.sh -O /tmp/default_script_installer.sh
# RUN chmod 755 /tmp/default_script_installer.sh
# RUN /tmp/default_script_installer.sh


RUN rm -rf /var/lib/{apt,dpkg,cache,log}/ /tmp/* /var/tmp/*
FROM builder_base_parkstay as python_libs_parkstay
WORKDIR /app
USER oim
RUN virtualenv /app/venv
ENV PATH=/app/venv/bin:$PATH
RUN git config --global --add safe.directory /app
COPY requirements.txt ./
RUN pip install --upgrade pip

RUN pip install --no-cache-dir -r requirements.txt

# Install the project (ensure that frontend projects have been built prior to this step).
FROM python_libs_parkstay

COPY --chown=oim:oim  python-cron ./
COPY --chown=oim:oim  startup.sh /
RUN chmod 755 /startup.sh
COPY --chown=oim:oim  gunicorn.ini manage.py ./
COPY .git ./.git
RUN touch /app/.env
RUN touch /app/git_hash
COPY --chown=oim:oim  parkstay ./parkstay
RUN mkdir -p /app/parkstay/cache/
RUN chmod 777 /app/parkstay/cache/

# RUN cd /app/parkstay/frontend/availability; npm ci --omit=dev && \
#     cd /app/parkstay/frontend/availability; npm run build

RUN cd /app/parkstay/frontend/parkstay; npm install
RUN cd /app/parkstay/frontend/parkstay; npm run build

RUN cd /app/parkstay/frontend/searchavail2; npm install
RUN cd /app/parkstay/frontend/searchavail2; npm run build         

RUN python manage.py collectstatic --noinput

EXPOSE 8080
HEALTHCHECK --interval=1m --timeout=5s --start-period=10s --retries=3 CMD ["wget", "-q", "-O", "-", "http://localhost:8080/"]
CMD ["/startup.sh"]
#CMD ["gunicorn", "parkstay.wsgi", "--bind", ":8080", "--config", "gunicorn.ini"]

