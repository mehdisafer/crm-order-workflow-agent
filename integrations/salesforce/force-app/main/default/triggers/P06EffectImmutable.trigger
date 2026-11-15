trigger P06EffectImmutable on P06_Effect__c (before insert, before update, before delete) {
    if (Trigger.isInsert) {
        for (P06_Effect__c effect : Trigger.new) {
            if (!P06OrderApi.isApplyingEffect()) {
                effect.addError('Effects can only be recorded by the conditional P06 endpoint.');
            }
        }
    } else {
        List<P06_Effect__c> committed = Trigger.isDelete ? Trigger.old : Trigger.new;
        for (P06_Effect__c effect : committed) {
            effect.addError('Committed workflow effects are immutable. Retain the audit record.');
        }
    }
}
