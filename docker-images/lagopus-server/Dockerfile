FROM node:12

WORKDIR /build/
COPY ./templates/package.json ./templates/
RUN cd templates && npm install

FROM tiangolo/meinheld-gunicorn:python3.7-alpine3.8

WORKDIR /app/
COPY --from=0 /build/ ./
COPY requirements.txt ./
RUN apk update && apk add postgresql-dev gcc python3-dev musl-dev
RUN pip install --no-cache-dir -r requirements.txt
COPY ./k8s ./k8s
COPY ./lagopus.py ./
COPY ./templates/. ./templates/

# meinheld dun werk
RUN sed -i -e 's/-k egg:meinheld#gunicorn_worker//' /start.sh

ENV MODULE_NAME="lagopus"
