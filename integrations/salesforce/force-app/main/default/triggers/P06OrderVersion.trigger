trigger P06OrderVersion on P06_Order__c (before insert, before update) {
    P06OrderGuard.validate(Trigger.new, Trigger.isUpdate ? Trigger.oldMap : null);
}
