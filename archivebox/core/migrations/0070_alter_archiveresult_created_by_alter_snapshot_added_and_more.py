# Generated by Django 5.1 on 2024-09-04 09:00

import abid_utils.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0069_alter_archiveresult_created_alter_snapshot_added_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='archiveresult',
            name='created_by',
            field=models.ForeignKey(default=abid_utils.models.get_or_create_system_user_pk, on_delete=django.db.models.deletion.CASCADE, related_name='archiveresult_set', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='snapshot',
            name='added',
            field=abid_utils.models.AutoDateTimeField(db_index=True, default=None),
        ),
        migrations.AlterField(
            model_name='snapshot',
            name='created',
            field=abid_utils.models.AutoDateTimeField(db_index=True, default=None),
        ),
        migrations.AlterField(
            model_name='snapshot',
            name='created_by',
            field=models.ForeignKey(default=abid_utils.models.get_or_create_system_user_pk, on_delete=django.db.models.deletion.CASCADE, related_name='snapshot_set', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='snapshot',
            name='id',
            field=models.UUIDField(default=None, primary_key=True, serialize=False, unique=True),
        ),
        migrations.AlterField(
            model_name='snapshot',
            name='old_id',
            field=models.UUIDField(default=None, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name='tag',
            name='created',
            field=abid_utils.models.AutoDateTimeField(db_index=True, default=None),
        ),
    ]
