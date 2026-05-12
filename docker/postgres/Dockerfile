FROM timescale/timescaledb:latest-pg16

COPY docker/postgres/init-multiple-databases.sh /docker-entrypoint-initdb.d/
RUN chmod +x /docker-entrypoint-initdb.d/init-multiple-databases.sh
