from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"

    def ready(self):
        # 2026-11-17: every sign-in starts the twelve hours and asks for a code
        # anew (apps/accounts/middleware.py).
        from django.contrib.auth.signals import user_logged_in

        from apps.accounts.middleware import stamp_sign_in

        user_logged_in.connect(stamp_sign_in, dispatch_uid="accounts.stamp_sign_in")
