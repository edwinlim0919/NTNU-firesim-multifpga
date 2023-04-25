#!/bin/bash

if [ $# -lt 3 ]; then
	echo "$0 [input] [n] [i]" >&2
	exit 1
fi

if [ $3 -lt 1 ] || [ $3 -gt $2 ]; then
	echo "Index must be bigger than zero and <= N!" >&2
	exit 1
fi

if [ ! -e "$1" ]; then
	echo "Could not find $1!" >&2
	exit 1
fi

cat "$1" | awk -v N=$2 -v i=$3 'NR==1{print; next}END{if((NR-1)%N!=(i-1))print;}(NR-1)%N==(i-1){print}'
