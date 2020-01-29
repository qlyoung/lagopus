FROM node:12

WORKDIR /build/
COPY . ./
RUN cd templates && npm install


FROM tiangolo/meinheld-gunicorn:python3.7

WORKDIR /app/
RUN pip install flask
COPY --from=0 /build/ ./

ENV MODULE_NAME="lagopus"
