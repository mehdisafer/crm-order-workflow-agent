@RestResource(urlMapping='/p06/v1/*')
global with sharing class P06OrderApi {
    private static Boolean effectInProgress = false;
    public static Boolean isApplyingEffect() { return effectInProgress; }

    // API 65 explicitly enforces CRUD/FLS and sharing. No arbitrary sObject writes.
    private class ApiException extends Exception {
        Integer status;
        String code;
        ApiException(Integer status, String code, String message) {
            this.status = status;
            this.code = code;
            this.setMessage(message);
        }
    }

    global class ChangeRequest {
        public String tenant_id;
        public String customer_id;
        public String effect_key;
        public Integer expected_revision;
        public String operation;
        public String requested_date;
        public String approved_plan_hash;
        public String expires_at;
        public String compensates_effect_key;
    }

    private static String correlation() {
        String value = RestContext.request.headers.get('X-Correlation-ID');
        if (String.isBlank(value)) value = RestContext.request.headers.get('x-correlation-id');
        if (String.isBlank(value) || !Pattern.matches('[A-Za-z0-9_.:-]{1,128}', value)) return 'unprovided';
        return value;
    }

    private static void send(Integer status, Object value) {
        RestContext.response.statusCode = status;
        RestContext.response.addHeader('Content-Type', 'application/json');
        RestContext.response.addHeader('X-Correlation-ID', correlation());
        RestContext.response.addHeader('Cache-Control', 'no-store');
        RestContext.response.responseBody = Blob.valueOf(JSON.serialize(value));
    }

    private static void fail(ApiException problem) {
        send(problem.status, new Map<String, Object>{
            'error' => new Map<String, Object>{
                'code' => problem.code, 'message' => problem.getMessage(),
                'retryable' => problem.status == 429 || problem.status >= 500
            }, 'correlation_id' => correlation()
        });
    }

    private static String requireText(String value, Integer maximum, String field) {
        if (String.isBlank(value) || value.length() > maximum) {
            throw new ApiException(400, 'invalid_request', 'Missing or invalid ' + field + '.');
        }
        return value;
    }

    private static String tenant(String requested) {
        requireText(requested, 80, 'tenant_id');
        if (!Schema.sObjectType.User.fields.P06_Tenant__c.isAccessible()) {
            throw new ApiException(403, 'permission_denied', 'Tenant binding is unavailable.');
        }
        User caller = [SELECT P06_Tenant__c FROM User WHERE Id = :UserInfo.getUserId() WITH USER_MODE];
        if (String.isBlank(caller.P06_Tenant__c) || caller.P06_Tenant__c != requested) {
            throw new ApiException(403, 'tenant_denied', 'The technical identity is not assigned to this tenant.');
        }
        return caller.P06_Tenant__c;
    }

    private static void requireRead() {
        if (!Schema.sObjectType.Account.isAccessible() || !Schema.sObjectType.P06_Order__c.isAccessible()
            || !Schema.sObjectType.P06_Effect__c.isAccessible()) {
            throw new ApiException(403, 'permission_denied', 'CRM read permissions are missing.');
        }
    }

    private static void requireWrite() {
        requireRead();
        if (!FeatureManagement.checkPermission('P06_Execute')
            || !Schema.sObjectType.P06_Order__c.isUpdateable()
            || !Schema.sObjectType.P06_Order__c.fields.Requested_Date__c.isUpdateable()
            || !Schema.sObjectType.P06_Order__c.fields.Last_Effect_Key__c.isUpdateable()
            || !Schema.sObjectType.P06_Effect__c.isCreateable()) {
            throw new ApiException(403, 'permission_denied', 'The technical identity cannot execute order changes.');
        }
    }

    private static List<String> route() {
        String prefix = '/services/apexrest/p06/v1/';
        String uri = RestContext.request.requestURI;
        if (!uri.startsWith(prefix)) throw new ApiException(404, 'not_found', 'Unknown endpoint.');
        return EncodingUtil.urlDecode(uri.substring(prefix.length()), 'UTF-8').split('/');
    }

    private static Id recordId(String raw) {
        if (raw == null || !Pattern.matches('[A-Za-z0-9]{15}([A-Za-z0-9]{3})?', raw)) {
            throw new ApiException(400, 'invalid_request', 'Invalid record identifier.');
        }
        try { return Id.valueOf(raw); }
        catch (Exception invalid) { throw new ApiException(400, 'invalid_request', 'Invalid record identifier.'); }
    }

    private static Map<String, Object> orderView(P06_Order__c order) {
        return new Map<String, Object>{
            'order_id' => order.Id, 'tenant_id' => order.Tenant__c,
            'customer_id' => order.Customer__c, 'reference' => order.Reference__c,
            'sku' => order.SKU__c, 'quantity' => order.Quantity__c,
            'requested_date' => String.valueOf(order.Requested_Date__c),
            'revision' => order.Revision__c.intValue(),
            'crm_url' => URL.getOrgDomainUrl().toExternalForm() + '/' + order.Id,
            'last_effect_key' => order.Last_Effect_Key__c
        };
    }

    private static P06_Order__c readOrder(Id id, String scope, Boolean lockRecord) {
        String query = 'SELECT Id, Tenant__c, Customer__c, Reference__c, SKU__c, Quantity__c, '
            + 'Requested_Date__c, Revision__c, Last_Effect_Key__c FROM P06_Order__c '
            + 'WHERE Id = :id AND Tenant__c = :scope';
        if (lockRecord) query += ' FOR UPDATE';
        List<P06_Order__c> rows = Database.queryWithBinds(query,
            new Map<String, Object>{'id' => id, 'scope' => scope}, AccessLevel.USER_MODE);
        if (rows.isEmpty()) throw new ApiException(404, 'not_found', 'Order is unavailable in this scope.');
        return rows[0];
    }

    @TestVisible
    private static String ledgerKey(String scope, String key) {
        requireText(key, 128, 'effect_key');
        if (!Pattern.matches('[A-Za-z0-9_.:-]{1,128}', key)) {
            throw new ApiException(400, 'invalid_request', 'Invalid effect key.');
        }
        return EncodingUtil.convertToHex(Crypto.generateDigest('SHA-256', Blob.valueOf(JSON.serialize(new List<String>{scope, key}))));
    }

    private static List<P06_Effect__c> findEffect(String scope, String key) {
        String compoundKey = ledgerKey(scope, key);
        return [SELECT Id, Effect_Key__c, Order__c, Request_Hash__c, Response_JSON__c,
                       Before_JSON__c, After_JSON__c, Plan_Hash__c, Compensates_Key__c
                FROM P06_Effect__c WHERE Key__c = :compoundKey AND Tenant__c = :scope WITH USER_MODE LIMIT 1];
    }

    @HttpGet
    global static void getResource() {
        try {
            List<String> parts = route();
            String requestedTenant = RestContext.request.params.get('tenant_id');
            if (parts.size() == 1 && parts[0] == 'capabilities' && String.isBlank(requestedTenant)) {
                requestedTenant = [SELECT P06_Tenant__c FROM User WHERE Id = :UserInfo.getUserId() WITH USER_MODE].P06_Tenant__c;
            }
            String scope = tenant(requestedTenant);
            requireRead();
            if (parts.size() == 1 && parts[0] == 'capabilities') {
                send(200, new Map<String, Object>{
                    'schema_version' => '1.0', 'provider' => 'salesforce',
                    'api_version' => '65.0', 'tenant_id' => scope,
                    'order_object' => 'P06_Order__c', 'effect_object' => 'P06_Effect__c',
                    'customer_object' => 'Account', 'integration_kind' => 'apex_rest',
                    'mutation_operations' => new List<String>{'change_delivery_date', 'compensate_delivery_date'},
                    'can_execute' => FeatureManagement.checkPermission('P06_Execute'),
                    'atomic_effect_ledger' => true, 'conditional_write' => true,
                    'permission_test_performed' => false
                });
            } else if (parts.size() == 1 && parts[0] == 'customers') {
                String ref = requireText(RestContext.request.params.get('reference'), 120, 'reference');
                List<Object> items = new List<Object>();
                for (Account customer : [SELECT Id, Name, P06_Reference__c, P06_Tenant__c FROM Account
                    WHERE P06_Tenant__c = :scope AND (P06_Reference__c = :ref OR Name = :ref)
                    WITH USER_MODE LIMIT 21]) {
                    items.add(new Map<String, Object>{'customer_id' => customer.Id,
                        'tenant_id' => customer.P06_Tenant__c, 'reference' => customer.P06_Reference__c,
                        'name' => customer.Name});
                }
                // >1 result is deliberately not resolved here: the application must clarify.
                send(200, new Map<String, Object>{'items' => items, 'truncated' => items.size() == 21});
            } else if (parts.size() == 1 && parts[0] == 'orders') {
                String ref = requireText(RestContext.request.params.get('reference'), 120, 'reference');
                Id customerId = recordId(RestContext.request.params.get('customer_id'));
                List<Object> items = new List<Object>();
                for (P06_Order__c order : [SELECT Id, Tenant__c, Customer__c, Reference__c, SKU__c,
                    Quantity__c, Requested_Date__c, Revision__c, Last_Effect_Key__c FROM P06_Order__c
                    WHERE Tenant__c = :scope AND Customer__c = :customerId AND Reference__c = :ref
                    WITH USER_MODE LIMIT 21]) items.add(orderView(order));
                send(200, new Map<String, Object>{'items' => items, 'truncated' => items.size() == 21});
            } else if (parts.size() == 2 && parts[0] == 'orders') {
                send(200, orderView(readOrder(recordId(parts[1]), scope, false)));
            } else if (parts.size() == 2 && parts[0] == 'effects') {
                List<P06_Effect__c> effects = findEffect(scope, parts[1]);
                if (effects.isEmpty()) throw new ApiException(404, 'not_found', 'Effect was not observed.');
                send(200, JSON.deserializeUntyped(effects[0].Response_JSON__c));
            } else throw new ApiException(404, 'not_found', 'Unknown endpoint.');
        } catch (ApiException problem) { fail(problem); }
        catch (QueryException denied) {
            fail(new ApiException(403, 'permission_denied', 'CRM fields or records are not accessible.'));
        } catch (Exception problem) {
            fail(new ApiException(500, 'crm_error', 'Read failed. Use the correlation identifier for investigation.'));
        }
    }

    @HttpPost
    global static void applyEffect() {
        Savepoint checkpoint;
        try {
            List<String> parts = route();
            if (parts.size() != 3 || parts[0] != 'orders' || parts[2] != 'effects') {
                throw new ApiException(404, 'not_found', 'Unknown endpoint.');
            }
            Blob body = RestContext.request.requestBody;
            if (body == null || body.size() > 8192) throw new ApiException(400, 'invalid_request', 'Invalid body size.');
            ChangeRequest request;
            try { request = (ChangeRequest) JSON.deserializeStrict(body.toString(), ChangeRequest.class); }
            catch (Exception invalid) { throw new ApiException(400, 'invalid_request', 'Body does not match the v1 contract.'); }
            if (request == null) throw new ApiException(400, 'invalid_request', 'Missing request.');
            String scope = tenant(request.tenant_id);
            requireWrite();
            Id id = recordId(parts[1]);
            Id customerId = recordId(request.customer_id);
            String compoundKey = ledgerKey(scope, request.effect_key);
            if (request.expected_revision == null || request.expected_revision < 1
                || request.approved_plan_hash == null || !Pattern.matches('[a-f0-9]{64}', request.approved_plan_hash)
                || (request.operation != 'change_delivery_date' && request.operation != 'compensate_delivery_date')) {
                throw new ApiException(400, 'invalid_request', 'Invalid revision, plan hash, or operation.');
            }
            Date requestedDate;
            Datetime expires;
            try {
                if (!Pattern.matches('\\d{4}-\\d{2}-\\d{2}', request.requested_date)) {
                    throw new ApiException(400, 'invalid_request', 'Invalid requested_date.');
                }
                requestedDate = Date.valueOf(request.requested_date);
                expires = (Datetime) JSON.deserialize(JSON.serialize(request.expires_at), Datetime.class);
                if (expires == null) throw new ApiException(400, 'invalid_request', 'Missing expires_at.');
            } catch (Exception invalid) { throw new ApiException(400, 'invalid_request', 'Invalid date or expiration.'); }
            if (request.operation == 'change_delivery_date' && request.compensates_effect_key != null) {
                throw new ApiException(400, 'invalid_request', 'Forward effects cannot reference a compensation.');
            }
            String requestHash = EncodingUtil.convertToHex(Crypto.generateDigest('SHA-256', Blob.valueOf(
                JSON.serialize(new List<Object>{scope, String.valueOf(id), String.valueOf(customerId),
                    request.effect_key, request.expected_revision, request.operation, request.requested_date,
                    request.approved_plan_hash, request.expires_at, request.compensates_effect_key}))));
            checkpoint = Database.setSavepoint();
            P06_Order__c current = readOrder(id, scope, true);
            if (current.Customer__c != customerId) throw new ApiException(409, 'scope_conflict', 'Customer and order do not match.');
            List<P06_Effect__c> duplicates = findEffect(scope, request.effect_key);
            if (!duplicates.isEmpty()) {
                if (duplicates[0].Request_Hash__c != requestHash || duplicates[0].Order__c != id) {
                    throw new ApiException(409, 'idempotency_conflict', 'Effect key was used for another immutable request.');
                }
                Map<String, Object> previous = (Map<String, Object>) JSON.deserializeUntyped(duplicates[0].Response_JSON__c);
                previous.put('replayed', true);
                send(200, previous);
                return;
            }
            // An expired replay can report existing evidence, but never produce a new effect.
            if (expires <= System.now()) throw new ApiException(409, 'approval_expired', 'The approved execution window expired.');
            if (current.Revision__c.intValue() != request.expected_revision) {
                throw new ApiException(409, 'state_conflict', 'Order changed after the approved snapshot.');
            }
            if (request.operation == 'compensate_delivery_date') {
                requireText(request.compensates_effect_key, 128, 'compensates_effect_key');
                List<P06_Effect__c> originals = findEffect(scope, request.compensates_effect_key);
                if (originals.isEmpty() || originals[0].Order__c != id || originals[0].Compensates_Key__c != null
                    || originals[0].Plan_Hash__c != request.approved_plan_hash) {
                    throw new ApiException(409, 'compensation_conflict', 'Original forward effect is not available in this scope.');
                }
                Map<String, Object> beforeOriginal = (Map<String, Object>) JSON.deserializeUntyped(originals[0].Before_JSON__c);
                Map<String, Object> afterOriginal = (Map<String, Object>) JSON.deserializeUntyped(originals[0].After_JSON__c);
                if (current.Last_Effect_Key__c != request.compensates_effect_key
                    || String.valueOf(current.Requested_Date__c) != String.valueOf(afterOriginal.get('requested_date'))
                    || request.expected_revision != Integer.valueOf(String.valueOf(afterOriginal.get('revision')))
                    || request.requested_date != String.valueOf(beforeOriginal.get('requested_date'))) {
                    throw new ApiException(409, 'compensation_conflict', 'A newer change prevents safe compensation.');
                }
            }
            Map<String, Object> beforeState = orderView(current);
            P06_Order__c change = new P06_Order__c(Id = id, Requested_Date__c = requestedDate,
                Last_Effect_Key__c = request.effect_key);
            effectInProgress = true;
            update as user change;
            P06_Order__c observed = readOrder(id, scope, false);
            Map<String, Object> afterState = orderView(observed);
            Map<String, Object> response = new Map<String, Object>{'effect_key' => request.effect_key,
                'order_id' => id, 'before' => beforeState, 'after' => afterState, 'replayed' => false,
                'approved_plan_hash' => request.approved_plan_hash, 'request_hash' => requestHash,
                'observed_revision' => observed.Revision__c.intValue()};
            P06_Effect__c effect = new P06_Effect__c(Key__c = compoundKey, Effect_Key__c = request.effect_key,
                Tenant__c = scope, Order__c = id, Request_Hash__c = requestHash,
                Plan_Hash__c = request.approved_plan_hash, Before_JSON__c = JSON.serialize(beforeState),
                After_JSON__c = JSON.serialize(afterState), Response_JSON__c = JSON.serialize(response),
                Compensates_Key__c = request.compensates_effect_key, Correlation_ID__c = correlation());
            insert as user effect;
            send(201, response);
        } catch (ApiException problem) {
            if (checkpoint != null) Database.rollback(checkpoint);
            fail(problem);
        } catch (DmlException rejected) {
            if (checkpoint != null) Database.rollback(checkpoint);
            String code = String.valueOf(rejected.getDmlType(0));
            if (code == 'UNABLE_TO_LOCK_ROW') {
                RestContext.response.addHeader('Retry-After', '2');
                fail(new ApiException(503, 'crm_busy', 'The CRM record is locked.'));
            } else if (code == 'DUPLICATE_VALUE') {
                fail(new ApiException(409, 'idempotency_conflict', 'Effect key is already in use. Reconcile the effect before retrying.'));
            } else fail(new ApiException(403, 'mutation_denied', 'CRM rejected the change. No effect was committed.'));
        } catch (QueryException inaccessibleOrLocked) {
            if (checkpoint != null) Database.rollback(checkpoint);
            RestContext.response.addHeader('Retry-After', '2');
            fail(new ApiException(503, 'crm_read_unavailable', 'Read or lock failed; verify permissions and retry budget.'));
        } catch (Exception problem) {
            if (checkpoint != null) Database.rollback(checkpoint);
            fail(new ApiException(500, 'crm_error', 'Execution failed. Reconcile by effect key before retrying.'));
        } finally {
            effectInProgress = false;
        }
    }
}
