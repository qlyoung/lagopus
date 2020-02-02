FROM node:12

WORKDIR /build/
COPY ./templates ./templates
COPY ./k8s ./k8s
RUN cd templates && npm install
COPY ./lagopus.py ./

FROM tiangolo/meinheld-gunicorn:python3.7

WORKDIR /app/
COPY --from=0 /build/ ./
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

ENV MODULE_NAME="lagopus"
