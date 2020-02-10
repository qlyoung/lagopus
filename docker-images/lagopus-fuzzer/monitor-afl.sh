#!/bin/bash
#
# AFL --> InfluxDB
# Gathers stats from AFL and adds them to InfluxDB.
#
# Copyright (C) 2019 Quentin Young
# Portions:
#    - Copyright 2015 Google LLC All rights reserved.
#
# Based on afl-whatsup by Michal Zalewski <lcamtuf@google.com>
#
# ----------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at:
#
#   http://www.apache.org/licenses/LICENSE-2.0

unset SUMMARY_ONLY

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

if [ "$#" -lt "1" ]; then
  echo "Usage: $0 -i <influx_host> -p <influx_port> -d <database> [ -s ] afl_sync_dir" 1>&2
  exit 1
fi

DIR="$1"

cd "$DIR" || exit 1

if [ -d queue ]; then
  echo "[-] Error: parameter is an individual output directory, not a sync dir." 1>&2
  exit 1
fi

CUR_TIME=$(date +%s)

TMP=$(mktemp -t .afl2influx-XXXXXXXX) || TMP=$(mktemp -p /data/local/tmp .afl2influx-XXXXXXXX) || exit 1

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
CURRENT_PATH=0
AVG_EPS=0

for i in $(find . -maxdepth 2 -iname fuzzer_stats | sort); do
  sed 's/[ ]*:[ ]*/="/;s/$/"/' "$i" >"$TMP"
  # Import fuzzer_stats into bash vars
  . "$TMP"

  RUN_UNIX=$((CUR_TIME - start_time))
  RUN_DAYS=$((RUN_UNIX / 60 / 60 / 24))
  RUN_HRS=$(((RUN_UNIX / 60 / 60) % 24))

  if ! kill -0 "$fuzzer_pid" 2>/dev/null; then
      echo "  Instance is dead or running remotely, skipping."
      echo
    DEAD_CNT=$((DEAD_CNT + 1))
    continue
  fi

  ALIVE_CNT=$((ALIVE_CNT + 1))

  #PATH_PERC=$((cur_path * 100 / paths_total))
  printf -v eps %.0f "$execs_per_sec"

  TOTAL_TIME=$((TOTAL_TIME + RUN_UNIX))
  TOTAL_EXECS=$((TOTAL_EXECS + execs_done))
  TOTAL_EPS=$((TOTAL_EPS + eps))
  TOTAL_CRASHES=$((TOTAL_CRASHES + unique_crashes))
  TOTAL_HANGS=$((TOTAL_HANGS + unique_hangs))
  TOTAL_PFAV=$((TOTAL_PFAV + pending_favs))
  TOTAL_PENDING=$((TOTAL_PENDING + pending_total))
  TOTAL_PATHS=$((TOTAL_PATHS + paths_total))
  CURRENT_PATH=$((CURRENT_PATH + cur_path))
done

rm -f "$TMP"

TOTAL_DAYS=$((TOTAL_TIME / 60 / 60 / 24))
TOTAL_HRS=$(((TOTAL_TIME / 60 / 60) % 24))
AVG_EPS=$(($TOTAL_EPS / $ALIVE_CNT))

test "$TOTAL_TIME" = "0" && TOTAL_TIME=1

echo "Pushing to database $INFLUX_DATABASE"

# Push to InfluxDB
TAGS="job_id=$JOB_ID"
TAGS="$TAGS,target=\"$(basename "$(echo "$command_line" | sed -n 's/^.*-- //p')")\""
TAGS="$TAGS,host=\"$(hostname)\""

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

