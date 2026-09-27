# Generated manually for the Prompt 5 circuit-breaker expiry field.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("news", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="sourcefeed",
            name="circuit_open_until",
            field=models.DateTimeField(blank=True, null=True),
        )
    ]
