#!/bin/bash
WD=$(pwd)

cd docker-images/lagopus-fuzzer
SHA=$(docker build -q . | cut -d':' -f2)
echo "Tagging fuzzer ($(pwd))"
docker tag $SHA qlyoung/lagopus-fuzzer:latest
docker push qlyoung/lagopus-fuzzer:latest
cd $WD

cd docker-images/lagopus-jobserver
docker build .
SHA=$(docker build -q . | cut -d':' -f2)
echo "Tagging jobserver ($(pwd))"
docker tag $SHA qlyoung/lagopus-jobserver:latest
docker push qlyoung/lagopus-jobserver:latest
cd $WD

rm lagopus.yaml
{
for file in ./jobserver/*.yaml; do
	cat $file
	printf "\n---\n"
done
for file in ./nfs/*.yaml; do
	cat $file
	printf "\n---\n"
done
} >> lagopus.yaml
