FROM node:12

WORKDIR /build/
COPY ./templates ./templates
COPY ./k8s ./k8s
RUN cd templates && npm install
COPY ./lagopus.py ./

FROM tiangolo/meinheld-gunicorn:python3.7

WORKDIR /app/
RUN pip install flask kubernetes
COPY --from=0 /build/ ./

ENV MODULE_NAME="lagopus"
