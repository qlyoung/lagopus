FROM qlyoung/fuzzbox:latest

RUN apt-get install -yqq zip unzip sysstat libcap2 libjson-c3

COPY entrypoint.sh /entrypoint.sh
COPY stop.sh /stop.sh

ENTRYPOINT [ "/entrypoint.sh" ]
