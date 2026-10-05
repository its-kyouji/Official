#!/bin/bash
docker build -t kyouji-relay .
docker run --rm -it -p 8080:8080 -e PROTO=vless -e IP="" kyouji-cli
