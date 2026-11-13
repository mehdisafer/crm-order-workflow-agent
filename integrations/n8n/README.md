# n8n intake workflow

Import `order-intake.workflow.json` into the authorized n8n instance, then bind the two Header Auth credentials in the editor. The workflow is inactive and contains no credential values or IDs. It forwards a stable source `message_id` to the application's requester API and returns its intake receipt. Temporal owns the durable workflow.

Target: n8n 2.47.5. Import and execution have not been verified in a running instance. See [vendor installation and qualification](../../docs/vendor-integration.md) for identities, private routing, evidence and licensing boundaries.
