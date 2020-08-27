#!/bin/bash
WD=$(pwd)

function build_tag_push() {
  printf ">>> Building docker image '%s'\n" "$1"
  cd docker-images/$1
  SHA=$(docker build -q . | cut -d':' -f2)
  echo "Tagging fuzzer ($(pwd))"
  docker tag $SHA qlyoung/$1:latest
  docker push qlyoung/$1:latest
  cd $WD
}

build_tag_push "lagopus-fuzzer"
build_tag_push "lagopus-server"
build_tag_push "lagopus-scanner"
build_tag_push "lagopus-db"

# rm lagopus.yaml
# {
# 	kubectl kustomize k8s/dev/
# } >> $WD/lagopus.yaml
