# Official HQ Kyouji Multiplex

Modular Cloud Run proxy backend utilizing Xray, Sing-box, Nginx, HAProxy, Envoy, and Caddy.

## ⚠️ Scaling Warning
`UUID` and `SUFFIX` generate dynamically per instance at startup. 
If scaling beyond `max-instances=1`, you **MUST** statically assign `UUID` and `SUFFIX` in the Cloud Run environment variables to prevent credentials from mismatching across different instances.

## Deployment
Use the included `custom-tools/deploy.sh` or Docker build logic.
Required Env: `$PORT` is injected by Cloud Run. Set `$IP`, `$PROTO`, and `$XPORT` for exit node pointing.
