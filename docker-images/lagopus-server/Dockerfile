FROM node:12

WORKDIR /build/
COPY ./templates/package.json ./templates/
RUN cd templates && npm install

FROM qlyoung/meinheld-gunicorn

WORKDIR /app/
COPY --from=0 /build/ ./
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY ./k8s ./k8s
COPY ./lagopus.py ./
COPY ./templates/. ./templates/

# meinheld dun werk
RUN sed -i -e 's/-k egg:meinheld#gunicorn_worker//' /start.sh

ENV MODULE_NAME="lagopus"
