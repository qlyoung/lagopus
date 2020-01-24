# Sets up a Docker image with Grafana, InfluxDB and AFL
# Grafana will monitor AFL's fuzzing progress and is accessible on port 3000

FROM qlyoung/fuzzbox:latest

COPY target.conf /opt/fuzz/target.conf
COPY entrypoint.sh /opt/entrypoint.sh
ENTRYPOINT [ "/opt/entrypoint.sh" ]
