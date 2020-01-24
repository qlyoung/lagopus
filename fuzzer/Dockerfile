FROM qlyoung/fuzzbox:latest

COPY target.conf /opt/fuzz/target.conf
COPY entrypoint.sh /opt/entrypoint.sh
ENTRYPOINT [ "/opt/entrypoint.sh" ]
