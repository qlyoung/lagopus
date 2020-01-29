#!/bin/bash
WD=$(pwd)

cd docker-images/lagopus-fuzzer
SHA=$(docker build -q . | cut -d':' -f2)
echo "Tagging fuzzer ($(pwd))"
docker tag $SHA qlyoung/lagopus-fuzzer:latest
docker push qlyoung/lagopus-fuzzer:latest
cd $WD

cd docker-images/lagopus-server
SHA=$(docker build -q . | cut -d':' -f2)
echo "Tagging server ($(pwd))"
docker tag $SHA qlyoung/lagopus-server:latest
docker push qlyoung/lagopus-server:latest
cd $WD

rm lagopus.yaml
{
	microk8s.kubectl kustomize k8s/dev/
} >> $WD/lagopus.yaml
