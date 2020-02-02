FROM mysql:8.0

COPY schema.sql /docker-entrypoint-initdb.d/schema.sql
ENV MYSQL_ROOT_PASSWORD=lagopus
ENV MYSQL_DATABASE=lagopus

EXPOSE 3306
