# CRM Order Workflow Agent

An auditable order-exception workflow for a fictional industrial customer-service team.

## Implementation status

The repository is being implemented under [issue #1](https://github.com/mehdisafer/crm-order-workflow-agent/issues/1). The initial inventory found an empty private repository.

The intended stack is Temporal for durable business workflows, PostgreSQL for transactional evidence and outbox dispatch, Salesforce reached through MuleSoft, and n8n for peripheral triggers. The stock service and all demonstration records are synthetic.

Provider acceptance requires an authorised Salesforce sandbox and MuleSoft runtime. No credentials or vendor environment were supplied at kickoff. A local synthetic profile is useful for development and does not constitute provider validation.

## Publication

The repository remains private. A licence has not been selected; the maintainer must explicitly decide before public distribution. Third-party components retain their own terms.
