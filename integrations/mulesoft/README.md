# P06 CRM System API

A tenant-bound Mule system API proxies reviewed requests to the actual Salesforce Apex service. It does not run a second saga. Start the reference runtime with `scripts/launch.sh` to disable the HTTP connector's implicit remotely-closed retries via actual JVM arguments, then inspect the selected process with `scripts/verify_runtime.py`. OAuth refresh on 401 remains an explicit, separately budgeted transport exception. It has an HTTPS listener, an allowlisted path/method surface, explicit OAuth client credentials, bounded concurrency and correlation-only logging.

See [vendor installation and qualification](../../docs/vendor-integration.md). Runtime target: Mule 4.9.24 / Java 17. This source package does not contain a Mule runtime distribution or license. XML/RAML source checks are separate from Maven packaging, deployment and live integration, all of which remain unverified without the required environment.
