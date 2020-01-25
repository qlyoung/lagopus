FROM qlyoung/fuzzbox:latest

RUN apt-get install -yqq zip unzip sysstat libcap2 libjson-c3
COPY lagopus-test-target.zip /opt/lagopus-test-target.zip

COPY entrypoint.sh /opt/entrypoint.sh
ENTRYPOINT [ "/opt/entrypoint.sh" ]
