This directory is a Docker project that defines the image used for running
fuzzing jobs within lagopus.

entrypoint.sh is the main program, handles the fuzzing, invoking post
processing, calling monitor stuff, moving results.

monitor-afl.sh is an afl-specific script to scrape fuzzer stats from a sync dir
and push them to influxdb. Called by entrypoint.sh.

analyzer has python stuff responsible for analyzing stack traces, extracting
types, symbolizing, determining security relevance, etc. This code is ripped
from ClusterFuzz and modified to work without the rest of it. Thanks Google!
