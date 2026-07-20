"""
Creates one demo user per role plus a superuser, so the system can be
explored immediately after `migrate` without manually creating accounts.

Usage: python manage.py seed_demo_data
"""
from django.core.management.base import BaseCommand
from apps.users.models import User


class Command(BaseCommand):
    help = "Seed demo users for every role (password: Passw0rd!123 for all)."

    def handle(self, *args, **options):
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser(username="admin", password="Passw0rd!123", role=User.Role.ADMIN)
            self.stdout.write(self.style.SUCCESS("Created superuser: admin"))

        demo_users = [
            ("merchandise1", User.Role.MERCHANDISE),
            ("store1", User.Role.STORE_MANAGER),
            ("cutting1", User.Role.CUTTING_SUPERVISOR),
            ("production1", User.Role.PRODUCTION_SUPERVISOR),
            ("finishing1", User.Role.FINISHING_SUPERVISOR),
            ("accounts1", User.Role.ACCOUNTS),
            ("operator1", User.Role.OPERATOR),
        ]
        created_users = {}
        for username, role in demo_users:
            user, was_created = User.objects.get_or_create(
                username=username, defaults={"role": role}
            )
            if was_created:
                user.set_password("Passw0rd!123")
                user.save()
                self.stdout.write(self.style.SUCCESS(f"Created {role}: {username}"))
            created_users[username] = user

        # Link operator1's login to an Operator profile, so the operator
        # self-service dashboard (/api/operators/assignments/my/, /income/my/)
        # has something to resolve against.
        from apps.operators.models import Operator
        operator_user = created_users.get("operator1")
        if operator_user and not Operator.objects.filter(user_account=operator_user).exists():
            Operator.objects.create(
                operator_type=Operator.OperatorType.INDIVIDUAL,
                name="Demo Operator (operator1)",
                skill_level=Operator.SkillLevel.INTERMEDIATE,
                is_active=True,
                user_account=operator_user,
            )
            self.stdout.write(self.style.SUCCESS("Linked Operator profile to operator1"))

        self.stdout.write(self.style.SUCCESS("Done. All demo users share password: Passw0rd!123"))
