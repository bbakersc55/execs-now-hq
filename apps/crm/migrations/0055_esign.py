"""E-signature (owner, 2026-10-29): a stage rule can send a document for
signature, and fire when a document is sent or signed. Additive."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0054_mailboxes'),
        ('esign', '0001_initial'),
        ('tenancy', '0023_calendar_secret'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Widened, not narrowed: a document trigger, like won and lost, names
        # no stage. Dropped and made again in one transaction.
        migrations.RemoveConstraint(
            model_name='stageautomation',
            name='stage_automation_stage_rule_has_a_stage',
        ),
        migrations.AddField(
            model_name='stageautomation',
            name='document_template',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='esign.documenttemplate'),
        ),
        migrations.AlterField(
            model_name='outboxmessage',
            name='producer',
            field=models.CharField(choices=[('stage_rule', 'Stage rule'), ('referral_touch', 'Referral touch'), ('referral_onboarding', 'Referral onboarding'), ('referral_thanks', 'Referral thank-you'), ('digest', 'Progress digest'), ('strategy_pdf', 'Strategy session PDF'), ('precall_invite', 'Pre-call invite'), ('precall_questions', 'Pre-call questions by email'), ('magic_link', 'Magic link'), ('note_pin_reset', 'Note PIN reset'), ('client_activity', 'Client activity notice'), ('pipeline_notices', 'Pipeline notices'), ('follow_up', 'Follow-up'), ('introduction', 'Introduction'), ('digest_reminder', 'Digest reminder'), ('precall_complete', 'Pre-call form completed'), ('cadence_change', 'Cadence change'), ('inbound_forward', 'Inbound forward'), ('campaign', 'Campaign'), ('manual', 'Manual'), ('practice_invite', 'Practice invitation'), ('feedback_notice', 'Feedback notice'), ('client_invoice', 'Invoice'), ('payment_receipt', 'Payment receipt'), ('payment_notice', 'Payment notice'), ('autopay_notice', 'Auto-pay notice'), ('subscription_receipt', 'Subscription receipt'), ('subscription_notice', 'Subscription notice'), ('signature_request', 'Signature request'), ('signature_reminder', 'Signature reminder'), ('signed_copy', 'Signed document')], db_index=True, max_length=24),
        ),
        migrations.AlterField(
            model_name='stageautomation',
            name='action_type',
            field=models.CharField(choices=[('create_task', 'Create a task'), ('draft_email', 'Draft an email into the Outbox'), ('move_stage', 'Move to another stage'), ('enroll_touches', 'Put on referral touches'), ('notify', 'Send a notice'), ('start_follow_up', "Start the stage's follow-up"), ('calendar_event', 'Offer a calendar event'), ('send_signature', 'Send a document for signature')], max_length=16),
        ),
        migrations.AlterField(
            model_name='stageautomation',
            name='trigger',
            field=models.CharField(choices=[('enters', 'Enters the stage'), ('idle', 'Has sat in the stage with no activity'), ('won', 'Is won'), ('lost', 'Is lost'), ('sent', 'Is sent a document to sign'), ('signed', 'Signs a document')], db_default='enters', default='enters', max_length=8),
        ),
        migrations.AddConstraint(
            model_name='stageautomation',
            constraint=models.CheckConstraint(condition=models.Q(('trigger__in', ['won', 'lost', 'sent', 'signed']), ('to_stage__isnull', False), _connector='OR'), name='stage_automation_stage_rule_has_a_stage'),
        ),
    ]
