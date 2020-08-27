FROM postgres:9.6.19

COPY schema.sql /docker-entrypoint-initdb.d/schema.sql
ENV POSTGRES_USER=lagopus
ENV POSTGRES_PASSWORD=lagopus
ENV POSTGRES_DB=lagopus

EXPOSE 5432
