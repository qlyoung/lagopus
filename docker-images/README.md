Containerized applications used lagopus.

- `lagopus-fuzzer`: The fuzzing container. Takes fuzzing jobs from a directory,
  runs them with the specified driver for the specified time, deposits the
  results into the directory.

- `lagopus-server`: The API / web server. Implements the web app and HTTP API
  for controlling and monitoring lagopus.
