public with sharing class P06OrderGuard {
    public static void validate(List<P06_Order__c> rows, Map<Id, P06_Order__c> oldRows) {
        Set<Id> customers = new Set<Id>();
        for (P06_Order__c row : rows) if (row.Customer__c != null) customers.add(row.Customer__c);
        Map<Id, Account> accounts = new Map<Id, Account>([
            SELECT Id, P06_Tenant__c FROM Account WHERE Id IN :customers WITH USER_MODE
        ]);
        for (P06_Order__c row : rows) {
            if (oldRows != null && FeatureManagement.checkPermission('P06_Execute')
                && !P06OrderApi.isApplyingEffect()) {
                row.addError('Technical executors must use the conditional P06 effect endpoint.');
                continue;
            }
            Account customer = accounts.get(row.Customer__c);
            if (customer == null || String.isBlank(row.Tenant__c) || row.Tenant__c != customer.P06_Tenant__c) {
                row.addError('Customer and order must belong to the same visible tenant.');
                continue;
            }
            if (row.Quantity__c == null || row.Quantity__c <= 0 || row.Requested_Date__c == null) {
                row.addError('Positive quantity and requested date are required.');
            }
            P06_Order__c previous = oldRows == null ? null : oldRows.get(row.Id);
            if (previous != null && (row.Tenant__c != previous.Tenant__c || row.Customer__c != previous.Customer__c)) {
                row.addError('Tenant and customer identities are immutable; create a reviewed replacement order.');
            }
            // Includes human/API edits, including changes to SKU, quantity and reference.
            row.Revision__c = previous == null ? 1 : previous.Revision__c + 1;
        }
    }
}
