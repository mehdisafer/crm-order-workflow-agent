# Durable workflow runtime

Temporal is the only component that advances the business saga. The API commits a request or approval and an outbox message in the same database transaction. n8n forwards intake. Neither the API nor n8n runs a second workflow engine.

## Execution contract

`OrderExceptionWorkflow` receives a case ID and bounded execution settings. Activities reload the authoritative case and approved plan from the transactional store. Workflow history contains the case ID, state, safe reason and approval deadline; customer names, CRM notes, request bodies, access tokens and plan contents are excluded by `workflow_snapshot`.

The durable sequence is:

1. `case.prepare` resolves identities and availability and stores a typed proposal.
2. A durable timer waits until the proposal's absolute expiration. `decision` is a wakeup signal with no approval payload. The next `prepare` reloads the committed decision.
3. `case.execute_crm` checks approval, current CRM state and stock. It reconciles the stable remote effect key before issuing any new write.
4. `case.reserve_stock` creates or observes the reservation with its own stable key.
5. `case.verify` rereads both systems before marking the case complete.
6. A failed reservation invokes `case.compensate`. The business service first checks for an already committed reservation, then checks whether a CRM compensation remains authorised and safe. A conflict stays visible as `RECONCILIATION_REQUIRED`.

Activity failure exhaustion calls `case.fail`. Cancellation also records a case outcome before the workflow closes; cancellation does not imply a rollback. Force termination cannot run cleanup and requires an explicit operator reconciliation.

## Delivery and retries

The dispatcher uses `case-{case_id}` as the workflow ID and `REJECT_DUPLICATE` for closed executions. After an uncertain start response, it describes the existing workflow and verifies its type and case/version memo. A matching execution is acknowledged; an unrelated collision is retained as a failed outbox delivery. An approval signal is pinned to the described run and cannot revive a closed workflow.

Outbox delivery is at least once. Two dispatchers may observe the same pending row; the receiver identities and signals are idempotent. A delayed dispatch failure cannot overwrite a successful acknowledgement. Exhausted messages enter the dead outbox and preserve their original identity during a controlled replay.

There is no workflow-level retry policy. Activities have a bounded attempt count, exponential backoff, Start-to-Close and Schedule-to-Close timeouts. Transient exceptions can carry `Retry-After`, which becomes `ApplicationError.next_retry_delay`; a long server delay can exhaust the total activity deadline rather than being shortened. Domain refusals and unexpected internal errors are not automatically retried.

HTTP adapters do not contain another business retry loop. The transactional store separately limits total API calls per case, remote write attempts, per-system concurrency and circuit cooldown across workers. Activity heartbeats permit cancellation and detect a dead worker; they contain only the operation name. Database leases survive a process crash until their bounded expiry.

All workers on a task queue must use the same `temporal_activity_rate_limit`: Temporal's task-queue rate setting is shared, and conflicting worker values would overwrite one another. The activity rate limit is not a guarantee of provider requests per second because an activity can make several bounded reads. Shared CRM/ERP admission limits apply to those calls.

## Executed recovery evidence

The following command was executed in the isolated Linux environment with Python 3.12.14, `temporalio` 1.36.0 and Temporal CLI 1.10.1, embedding Server 1.32.2 and UI 2.56.4:

```bash
RUN_TEMPORAL_TESTS=1 .venv/bin/pytest -q \
  tests/test_temporal.py tests/test_temporal_core.py tests/test_dispatcher.py
```

Observed result at this implementation checkpoint: **20 passed in 36.06 seconds**. The final repository evidence may include additional tests and another recorded duration.

| Executed scenario | What the test proves | Boundary |
| --- | --- | --- |
| `test_process_crash_after_crm_commit_recovers_without_duplicate` | A separate worker process exits with code 86 immediately after the persistent synthetic CRM commits and before its acknowledgement. A replacement worker recovers the `UNKNOWN` journal, completes, and leaves exactly one CRM effect and one reservation. The CRM write-attempt count remains one. | Real process death, Temporal server and business database; synthetic CRM/ERP. |
| `test_server_and_worker_restart_recover_outbox_and_approval` | Temporal restarts from its SQLite history file. Business runtime objects are recreated. An approval committed during downtime and an unacknowledged successful workflow start are recovered without a second workflow or remote effect. | Real server persistence and application state recovery; not a PostgreSQL or provider failover test. |
| `test_approval_is_database_authority_and_history_is_minimised` | A signal without a stored approval cannot cause a write; duplicate signals do not add effects; a CRM note marker is absent from workflow history. | Real orchestration with explicit synthetic activity fixtures. |
| `test_stock_refusal_uses_guarded_compensation` | Stock refusal follows the compensation branch; a later human-edit fixture changes the outcome to reconciliation. | Orchestration contract, complemented by business-core policy tests. |
| Retry, expiry and cancellation tests | Exhausted retries and expired approval are visible and bounded; cancellation records a case outcome. | No real provider permission claim. |
| Outbox and slot regressions | Late failure does not mark a delivered event dead; observed effects cannot be downgraded; concurrent release preserves shared failure counters. | SQLite concurrency regression, with PostgreSQL deployment validation remaining a separate gate. |

Completed histories are passed to Temporal's `Replayer`. Replay verifies that this workflow code reproduces the recorded commands; it is not a substitute for remote effect reconciliation.

The profile is explicit: without `RUN_TEMPORAL_TESTS=1`, these tests are skipped. When the profile is requested, a server startup or download failure fails the tests instead of turning them into a silent skip. `TEMPORAL_CLI_PATH` can select an already provisioned official CLI binary.

## Deployment and upgrades

The reference Compose deployment persists the Temporal development server's SQLite history and uses PostgreSQL for business state. It is a single-host demonstration profile. The Temporal CLI explicitly describes `start-dev` as unsuitable for production; production deployment requires a supported Temporal service, security configuration, retention and operational ownership.

Before changing activity names, ordering, signal semantics or workflow input shape, replay recorded histories and plan a compatible rollout. The current release has one workflow contract version. Do not reset or delete histories to force code through a compatibility failure. Keep old code available for existing executions or adopt an explicit Temporal worker versioning strategy before that becomes necessary.

## Official references

- [Temporal Python workflow execution and retries](https://docs.temporal.io/develop/python)
- [Activity retry policies and unlimited default attempts](https://docs.temporal.io/encyclopedia/retry-policies)
- [ApplicationError and next_retry_delay](https://python.temporal.io/temporalio.exceptions.ApplicationError.html)
- [Worker concurrency, task-queue rates and graceful shutdown](https://python.temporal.io/temporalio.worker.Worker.html)
- [WorkflowEnvironment persistence and local-server testing](https://python.temporal.io/temporalio.testing.WorkflowEnvironment.html)
- [Temporal Python cancellation semantics](https://github.com/temporalio/sdk-python#asyncio-cancellation)
- [Temporal CLI 1.10.1 release](https://github.com/temporalio/cli/releases/tag/v1.10.1)
