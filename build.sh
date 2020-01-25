#!/bin/bash
{
for file in ./jobserver/*.yaml; do
	cat $file
	printf "\n---\n"
done
} >> lagopus.yaml
