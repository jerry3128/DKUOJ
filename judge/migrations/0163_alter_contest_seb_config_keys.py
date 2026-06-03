from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('judge', '0162_alter_contest_options_contest_seb_browser_exam_keys_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='contest',
            name='seb_config_keys',
            field=models.TextField(blank=True, default='', help_text='One 64-char hex hash per line. Required for macOS clients (and any newer build that sends only the Config Key).', verbose_name='allowed SEB Config Key hashes'),
        ),
    ]
