# Salesforce synthetic order extension

This source package adds a dedicated order object and immutable effect ledger, Account/User scope fields, narrow permission sets, a revision trigger and a conditional Apex REST API. It uses actual Salesforce objects and execution when installed. It does not assume standard Order, Commerce, CPQ or an edition-specific product is available.

The API changes only a synthetic delivery date covered by the application's approved plan. Scope, permissions, expiration, revision, idempotency and compensation are checked again remotely. No Salesforce tenant was supplied here: compilation, deployment and the Apex test suite remain unexecuted.

See [vendor installation and qualification](../../docs/vendor-integration.md) before using the scripts. `seed.apex.example` is a reviewed administrator template, not an automatically executed migration.
