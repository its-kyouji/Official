# Official Relay Core (Kyouji Architecture)

Production-grade, multiplexed container runtime engineered for Google Cloud Run. Consolidates Xray-core, Sing-box, OpenSSH, Dropbear, BadVPN, and OpenVPN relay capabilities behind a strict non-overlapping proxy chain.

## Cloud Run Service Settings
*   **Port:** 8080 (Managed via `$PORT`)
*   **Request Timeout:** 3600 seconds
*   **Concurrency:** 1000
*   **Min Instances:** 1 (Mandatory to prevent cold-start scale-to-zero dropping long-lived streams)
*   **Execution Environment:** gen2
*   **CPU Allocation:** --no-cpu-throttling (Always-on CPU required for continuous proxy tunneling)

## Important Operational Note on Dynamic IDs
By default, `UUID` and `SUFFIX` are generated dynamically per instance startup if left blank. When scaling your Cloud Run deployment beyond `min-instances=1`, you **must** explicitly define `UUID` and `SUFFIX` in your environment variables to ensure consistent client link distribution across instances.
