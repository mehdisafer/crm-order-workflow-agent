@IsTest
private class P06OrderApiTest {
    private static final String TENANT = 'demo-industrial';
    private static final String PLAN = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

    @TestSetup
    static void setupData() {
        // Fail clearly if this standard least-privilege profile is absent; never use an admin fallback.
        Id minimumProfile = [SELECT Id FROM Profile WHERE Name = 'Minimum Access - Salesforce' LIMIT 1].Id;
        List<User> users = new List<User>();
        for (String role : new List<String>{'writer', 'reader'}) {
            users.add(new User(LastName = 'P06 ' + role, Alias = role,
                Email = role + '@example.invalid', Username = role + '.' + UserInfo.getOrganizationId()
                    + '.' + System.now().getTime() + '@p06.example.invalid',
                TimeZoneSidKey = 'Europe/Paris', LocaleSidKey = 'en_US', EmailEncodingKey = 'UTF-8',
                LanguageLocaleKey = 'en_US', ProfileId = minimumProfile, P06_Tenant__c = TENANT));
        }
        insert users;
        Map<String, Id> permissionIds = new Map<String, Id>();
        for (PermissionSet permission : [SELECT Id, Name FROM PermissionSet WHERE Name IN ('P06_Executor','P06_Reader')]) {
            permissionIds.put(permission.Name, permission.Id);
        }
        insert new List<PermissionSetAssignment>{
            new PermissionSetAssignment(AssigneeId = users[0].Id, PermissionSetId = permissionIds.get('P06_Executor')),
            new PermissionSetAssignment(AssigneeId = users[1].Id, PermissionSetId = permissionIds.get('P06_Reader'))
        };
        System.runAs(new User(Id = UserInfo.getUserId())) {
            Account account = new Account(Name = 'Synthetic Alloy Works', P06_Reference__c = 'CUST-001',
                P06_Tenant__c = TENANT, OwnerId = users[0].Id);
            insert account;
            P06_Order__c order = new P06_Order__c(Customer__c = account.Id, Tenant__c = TENANT,
                Reference__c = 'ORD-1001', SKU__c = 'SKU-001', Quantity__c = 10,
                Requested_Date__c = Date.today().addDays(7), OwnerId = users[0].Id);
            insert order;
            insert new AccountShare(AccountId = account.Id, UserOrGroupId = users[1].Id,
                AccountAccessLevel = 'Read', OpportunityAccessLevel = 'None', CaseAccessLevel = 'None');
            insert new P06_Order__Share(ParentId = order.Id, UserOrGroupId = users[1].Id, AccessLevel = 'Read');
        }
    }

    private static User actor(String role) {
        String familyName = 'P06 ' + role;
        return [SELECT Id FROM User WHERE Alias = :role AND LastName = :familyName LIMIT 1];
    }
    private static P06_Order__c order() { return [SELECT Id, Customer__c, Requested_Date__c, Revision__c FROM P06_Order__c LIMIT 1]; }

    private static Map<String,Object> request(P06_Order__c row, String key) {
        return new Map<String,Object>{'tenant_id' => TENANT, 'customer_id' => row.Customer__c,
            'effect_key' => key, 'expected_revision' => row.Revision__c.intValue(),
            'operation' => 'change_delivery_date', 'requested_date' => String.valueOf(Date.today().addDays(10)),
            'approved_plan_hash' => PLAN, 'expires_at' => System.now().addMinutes(10).formatGmt('yyyy-MM-dd\'T\'HH:mm:ss.SSS\'Z\'')};
    }

    private static Map<String,Object> post(Id id, Map<String,Object> payload) {
        RestContext.request = new RestRequest();
        RestContext.response = new RestResponse();
        RestContext.request.httpMethod = 'POST';
        RestContext.request.requestURI = '/services/apexrest/p06/v1/orders/' + id + '/effects';
        RestContext.request.addHeader('X-Correlation-ID', 'p06-apex-test');
        RestContext.request.requestBody = Blob.valueOf(JSON.serialize(payload));
        P06OrderApi.applyEffect();
        return (Map<String,Object>)JSON.deserializeUntyped(RestContext.response.responseBody.toString());
    }

    private static Map<String,Object> get(String resource, Map<String,String> params) {
        RestContext.request = new RestRequest();
        RestContext.response = new RestResponse();
        RestContext.request.httpMethod = 'GET';
        RestContext.request.requestURI = '/services/apexrest/p06/v1/' + resource;
        for (String key : params.keySet()) RestContext.request.addParameter(key, params.get(key));
        P06OrderApi.getResource();
        return (Map<String,Object>)JSON.deserializeUntyped(RestContext.response.responseBody.toString());
    }

    @IsTest static void effectIsAtomicAndReplayDoesNotDuplicate() {
        P06_Order__c row = order();
        Map<String,Object> payload = request(row, 'forward-1');
        System.runAs(actor('writer')) {
            Map<String,Object> first = post(row.Id, payload);
            System.assertEquals(201, RestContext.response.statusCode);
            System.assertEquals(false, first.get('replayed'));
            Map<String,Object> replay = post(row.Id, payload);
            System.assertEquals(200, RestContext.response.statusCode);
            System.assertEquals(true, replay.get('replayed'));
            System.assertEquals(1, [SELECT COUNT() FROM P06_Effect__c]);
            System.assertEquals(2, order().Revision__c);
            Map<String,Object> observed = get('effects/forward-1', new Map<String,String>{'tenant_id'=>TENANT});
            System.assertEquals('forward-1', observed.get('effect_key'));
            payload.put('requested_date', String.valueOf(Date.today().addDays(11)));
            post(row.Id, payload);
            System.assertEquals(409, RestContext.response.statusCode);
            System.assertEquals(2, order().Revision__c);
        }
    }

    @IsTest static void lostResponseCanBeReconciledAndCompensated() {
        P06_Order__c initial = order();
        System.runAs(actor('writer')) {
            post(initial.Id, request(initial, 'lost-response'));
            System.assertEquals(201, RestContext.response.statusCode);
            // A real transport-loss test must still run through MuleSoft; this only tests the ledger semantics.
            Map<String,Object> evidence = get('effects/lost-response', new Map<String,String>{'tenant_id'=>TENANT});
            System.assertEquals('lost-response', evidence.get('effect_key'));
            P06_Order__c changed = order();
            Map<String,Object> undo = request(changed, 'undo-1');
            undo.put('operation', 'compensate_delivery_date');
            undo.put('compensates_effect_key', 'lost-response');
            undo.put('requested_date', String.valueOf(initial.Requested_Date__c));
            post(initial.Id, undo);
            System.assertEquals(201, RestContext.response.statusCode);
            System.assertEquals(initial.Requested_Date__c, order().Requested_Date__c);
            System.assertEquals(3, order().Revision__c);
            System.assertEquals(2, [SELECT COUNT() FROM P06_Effect__c]);
        }
    }

    @IsTest static void humanEditPreventsCompensation() {
        P06_Order__c initial = order();
        System.runAs(actor('writer')) {
            post(initial.Id, request(initial, 'human-conflict'));
            System.assertEquals(201, RestContext.response.statusCode);
        }
        Date humanDate = Date.today().addDays(14);
        update new P06_Order__c(Id = initial.Id, Requested_Date__c = humanDate);
        System.assertEquals(3, order().Revision__c);
        System.runAs(actor('writer')) {
            Map<String,Object> undo = request(order(), 'undo-conflict');
            undo.put('operation','compensate_delivery_date');
            undo.put('compensates_effect_key','human-conflict');
            undo.put('requested_date',String.valueOf(initial.Requested_Date__c));
            post(initial.Id, undo);
            System.assertEquals(409, RestContext.response.statusCode);
            System.assertEquals(humanDate, order().Requested_Date__c);
            System.assertEquals(1, [SELECT COUNT() FROM P06_Effect__c]);
        }
    }

    @IsTest static void expirationRevisionAndSchemaAreEnforced() {
        P06_Order__c row = order();
        System.runAs(actor('writer')) {
            Map<String,Object> payload = request(row, 'expired');
            payload.put('expires_at', System.now().addSeconds(-10).formatGmt('yyyy-MM-dd\'T\'HH:mm:ss.SSS\'Z\''));
            post(row.Id,payload);
            System.assertEquals(409,RestContext.response.statusCode);
            payload = request(row, 'stale'); payload.put('expected_revision',99);
            post(row.Id,payload);
            System.assertEquals(409,RestContext.response.statusCode);
            payload = request(row, 'injection'); payload.put('discount',50);
            post(row.Id,payload);
            System.assertEquals(400,RestContext.response.statusCode);
            payload = request(row, 'operation'); payload.put('operation','grant_discount');
            post(row.Id,payload);
            System.assertEquals(400,RestContext.response.statusCode);
            System.assertEquals(0,[SELECT COUNT() FROM P06_Effect__c]);
            System.assertEquals(1,order().Revision__c);
        }
    }

    @IsTest static void readerCannotWriteAndTenantCannotBeForged() {
        P06_Order__c row = order();
        System.runAs(actor('reader')) {
            post(row.Id, request(row,'reader-denial'));
            System.assertEquals(403,RestContext.response.statusCode);
            get('orders/'+row.Id,new Map<String,String>{'tenant_id'=>TENANT});
            System.assertEquals(200,RestContext.response.statusCode);
            get('orders/'+row.Id,new Map<String,String>{'tenant_id'=>'other-tenant'});
            System.assertEquals(403,RestContext.response.statusCode);
        }
        System.assertEquals(1,order().Revision__c);
    }

    @IsTest static void customerLookupAndCapabilitiesExposeObservedScope() {
        P06_Order__c row = order();
        Account sameReference = new Account(Name='Synthetic Alloy Works Duplicate',
            P06_Reference__c='CUST-001',P06_Tenant__c=TENANT,OwnerId=actor('writer').Id);
        insert sameReference;
        System.runAs(actor('writer')) {
            Map<String,Object> customers = get('customers',new Map<String,String>{'tenant_id'=>TENANT,'reference'=>'CUST-001'});
            System.assertEquals(2,((List<Object>)customers.get('items')).size());
            Map<String,Object> orders = get('orders',new Map<String,String>{'tenant_id'=>TENANT,
                'customer_id'=>String.valueOf(row.Customer__c),'reference'=>'ORD-1001'});
            System.assertEquals(1,((List<Object>)orders.get('items')).size());
            Map<String,Object> capabilities = get('capabilities',new Map<String,String>{'tenant_id'=>TENANT});
            System.assertEquals('salesforce',capabilities.get('provider'));
            System.assertEquals(true,capabilities.get('can_execute'));
            get('effects/unobserved',new Map<String,String>{'tenant_id'=>TENANT});
            System.assertEquals(404,RestContext.response.statusCode);
            get('unknown',new Map<String,String>{'tenant_id'=>TENANT});
            System.assertEquals(404,RestContext.response.statusCode);
        }
    }

    @IsTest static void technicalWriterCannotBypassEffectEndpoint() {
        P06_Order__c row = order();
        System.runAs(actor('writer')) {
            Database.SaveResult result = Database.update(new P06_Order__c(Id=row.Id,
                Requested_Date__c=Date.today().addDays(20)),false,AccessLevel.USER_MODE);
            System.assertEquals(false,result.isSuccess());
            System.assertEquals(1,order().Revision__c);
            post(row.Id,request(row,'immutable'));
            System.assertEquals(201,RestContext.response.statusCode);
        }
        P06_Effect__c effect = [SELECT Id FROM P06_Effect__c LIMIT 1];
        Database.DeleteResult removed = Database.delete(effect,false);
        System.assertEquals(false,removed.isSuccess());
    }

    @IsTest static void scopedKeysRemainDistinctWhenIdentifiersContainColons() {
        System.assertNotEquals(P06OrderApi.ledgerKey('tenant:part', 'effect'),
            P06OrderApi.ledgerKey('tenant', 'part:effect'),
            'Tenant and effect key must be encoded as distinct values before hashing.');
        System.assertEquals(P06OrderApi.ledgerKey('tenant:part', 'effect'),
            P06OrderApi.ledgerKey('tenant:part', 'effect'));
    }
}
