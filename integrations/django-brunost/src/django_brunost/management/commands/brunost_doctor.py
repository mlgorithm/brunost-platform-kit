from django.core.management.base import BaseCommand

from brunost_platform.gateway import gateway_from_environment


class Command(BaseCommand):
    help = "Check connectivity to the configured Brunost Judge"

    def handle(self, *args, **options):
        self.stdout.write(str(gateway_from_environment().health()))
