from django.core.management.base import BaseCommand

from django_brunost.services import dispatch_pending_submissions


class Command(BaseCommand):
    help = "Dispatch queued Brunost submissions through the durable outbox."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        results = dispatch_pending_submissions(limit=options["limit"])
        self.stdout.write(self.style.SUCCESS(f"processed {len(results)} submission outbox entries"))
