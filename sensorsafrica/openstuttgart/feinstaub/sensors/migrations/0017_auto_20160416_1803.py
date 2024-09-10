# -*- coding: utf-8 -*-
# Generated by Django 1.9 on 2016-04-16 18:03
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sensors', '0016_auto_20160209_2030'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sensordatavalue',
            name='value_type',
            field=models.CharField(choices=[('P1', '1µm particles'), ('P2', '2.5µm particles'), ('durP1', 'duration 1µm'), ('durP2', 'duration 2.5µm'), ('ratioP1', 'ratio 1µm in percent'), ('ratioP2', 'ratio 2.5µm in percent'), ('samples', 'samples'), ('min_micro', 'min_micro'), ('max_micro', 'max_micro'), ('temperature', 'Temperature'), ('humidity', 'Humidity'), ('pressure', 'Pa'), ('altitude', 'meter'), ('pressure_sealevel', 'Pa (sealevel)'), ('brightness', 'Brightness'), ('dust_density', 'Dust density in mg/m3'), ('vo_raw', 'Dust voltage raw'), ('voltage', 'Dust voltage calculated'), ('P10', '1µm particles'), ('P25', '2.5µm particles'), ('durP10', 'duration 1µm'), ('durP25', 'duration 2.5µm'), ('ratioP10', 'ratio 1µm in percent'), ('ratioP25', 'ratio 2.5µm in percent'), ('door_state', 'door state (open/closed)')], db_index=True, max_length=100),
        ),
    ]
