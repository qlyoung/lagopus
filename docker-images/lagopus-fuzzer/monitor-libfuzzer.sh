#!/bin/bash
#
# libFuzzer --> InfluxDB
# Gathers stats from libFuzzer logs and adds them to InfluxDB.
#
# Copyright (C) 2019 Quentin Young

INFLUX_HOST=""
INFLUX_PORT=8086
INFLUX_DATABASE=""
INFLUX_MEASUREMENT=""

while getopts "i:p:d:m:" opt; do
  case "$opt" in
    i)
      INFLUX_HOST=$OPTARG
      ;;
    p)
      INFLUX_PORT=$OPTARG
      ;;
    d)
      INFLUX_DATABASE=$OPTARG
      ;;
    m)
      INFLUX_MEASUREMENT=$OPTARG
      ;;
  esac
done
shift $((OPTIND-1))

CUR_TIME=$(date +%s)

ALIVE_CNT=0
DEAD_CNT=0

TOTAL_TIME=0
TOTAL_EXECS=0
TOTAL_EPS=0
TOTAL_CRASHES=0
TOTAL_HANGS=0
TOTAL_PFAV=0
TOTAL_PENDING=0
TOTAL_PATHS=0
TOTAL_HRS=0
CURRENT_PATH=0
AVG_EPS=0

for file in ./fuzz-*.log; do
	IFS=$'\n'
	STATS=($(grep 'cov' "$file" | sed -e 's/^.*cov/cov/g' | tail -n 1 | tr -s ' ' | cut -d' ' -f2,4,6,8,10,12 | tr -s ' ' '\n' | sed -e 's/[A-Z][a-z]//g'))
	unset IFS

	TOTAL_PATHS=$((TOTAL_PATHS + STATS[0]))
	TOTAL_EPS=$((TOTAL_EPS + STATS[4]))
done

TOTAL_CRASHES=$(find . -maxdepth 1 -type f \( -name "crash-*" -o -name "leak-*" \) | wc -l)
TOTAL_HANGS=$(find . -maxdepth 1 -type f -name "timeout-*" | wc -l)

echo "Pushing to database $INFLUX_DATABASE"

# Push to InfluxDB
TAGS="job_id=$JOB_ID"
TAGS="$TAGS,target=target"
TAGS="$TAGS,host=$HOSTNAME"

FIELDS="alive=$ALIVE_CNT"
FIELDS="$FIELDS,crashes=$TOTAL_CRASHES"
FIELDS="$FIELDS,hangs=$TOTAL_HANGS"
FIELDS="$FIELDS,execs_per_sec=$TOTAL_EPS"
FIELDS="$FIELDS,execs=$TOTAL_EXECS"
FIELDS="$FIELDS,pending=$TOTAL_PENDING"
FIELDS="$FIELDS,pending_fav=$TOTAL_PFAV"
FIELDS="$FIELDS,total_paths=$TOTAL_PATHS"
FIELDS="$FIELDS,current_path=$CURRENT_PATH"
FIELDS="$FIELDS,cpu_hours=$TOTAL_HRS"

echo "Creating DB"
influx -host "$INFLUX_HOST" -port "$INFLUX_PORT" -execute "CREATE DATABASE \"$INFLUX_DATABASE\""

CMD="influx -host \"$INFLUX_HOST\" -port \"$INFLUX_PORT\" -database \"$INFLUX_DATABASE\" -execute \"INSERT INTO autogen $INFLUX_MEASUREMENT,$TAGS $FIELDS\""
echo "Executing: $CMD"
eval "$CMD"

exit 0

