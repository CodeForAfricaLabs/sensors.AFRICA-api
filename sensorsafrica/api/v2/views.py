import datetime
import pytz
import json

from rest_framework.exceptions import ValidationError

from django.conf import settings
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from django.db.models import ExpressionWrapper, F, FloatField, Max, Min, Sum, Avg, Q
from django.db.models.functions import Cast, TruncDay, TruncHour, TruncMinute, TruncMonth
from rest_framework import mixins, pagination, viewsets

from django.db import connection

from ..models import LastActiveNodes, City, Node
from .serializers import RawSensorDataStatSerializer, CitySerializer

from feinstaub.sensors.views import StandardResultsSetPagination

from feinstaub.sensors.models import SensorLocation, SensorData, SensorDataValue

from django.utils.text import slugify

from rest_framework.response import Response

from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

value_types = {"air": ["P1", "P2", "humidity", "temperature"]}


def beginning_of_today():
    return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)


def end_of_today():
    return beginning_of_today() + datetime.timedelta(hours=24)


def beginning_of_day(from_date):
    return datetime.datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=pytz.UTC)


def end_of_day(to_date):
    return beginning_of_day(to_date) + datetime.timedelta(hours=24)


def validate_date(date_text, error):
    try:
        datetime.datetime.strptime(date_text, "%Y-%m-%d")
    except ValueError:
        raise ValidationError(error)


class CustomPagination(pagination.PageNumberPagination):
    page_size_query_param = "page_size"
    max_page_size = 1000
    page_size = 100

    def get_paginated_response(self, data_stats):
        # If filtering from a date
        # We will need to have a list of the value_types e.g. { 'P1': [{}, {}] }
        from_date = self.request.query_params.get("from", None)

        results = {}
        for data_stat in data_stats:
            city_name = data_stat["city_name"]
            value_type = data_stat["value_type"]

            if city_name not in results:
                results[city_name] = {
                    "city_name": city_name,
                    value_type: [] if from_date else {},
                }

            if value_type not in results[city_name]:
                results[city_name][value_type] = [] if from_date else {}

            values = results[city_name][value_type]
            include_result = getattr(
                values, "append" if from_date else "update")
            include_result(
                {
                    "average": data_stat["average"],
                    "minimum": data_stat["minimum"],
                    "maximum": data_stat["maximum"],
                    "start_datetime": data_stat["start_datetime"],
                    "end_datetime": data_stat["end_datetime"],
                }
            )

        return Response(
            {
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "count": len(results.keys()),
                "results": list(results.values()),
            }
        )


class SensorDataStatView(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = RawSensorDataStatSerializer
    pagination_class = CustomPagination

    @method_decorator(cache_page(3600))
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        sensor_type = self.kwargs["sensor_type"]

        city_names = self.request.query_params.get("city", None)
        from_date = self.request.query_params.get("from", None)
        to_date = self.request.query_params.get("to", None)
        avg = self.request.query_params.get("avg", 'day')

        if to_date and not from_date:
            raise ValidationError(
                {"from": "Must be provide along with to query"})
        if from_date:
            validate_date(
                from_date, {"from": "Must be a date in the format Y-m-d."})
        if to_date:
            validate_date(
                to_date, {"to": "Must be a date in the format Y-m-d."})

        value_type_to_filter = self.request.query_params.get(
            "value_type", None)

        filter_value_types = value_types[sensor_type]
        if value_type_to_filter:
            filter_value_types = set(value_type_to_filter.upper().split(",")) & set(
                [x.upper() for x in value_types[sensor_type]]
            )

        if not from_date and not to_date:
            to_date = timezone.now()
            from_date = to_date - datetime.timedelta(hours=24)
        elif not to_date:
            from_date = beginning_of_day(from_date)
            # Get data from_date until the end
            # of day yesterday which is the beginning of today
            to_date = beginning_of_today()
        else:
            from_date = beginning_of_day(from_date)
            to_date = end_of_day(to_date)

        city_names = city_names.split(',') if city_names else []

        with connection.cursor() as cursor:
            cursor.execute("""
                    SELECT
                        sl.city as city_name,
                        min(sd."timestamp") as start_datetime,
                        max(sd."timestamp") as end_datetime,
                        sum(CAST("value" as float)) / COUNT(*) AS average,
                        min(CAST("value" as float)) as minimum,
                        max(CAST("value" as float)) as maximum,
                        v.value_type,
                        STRING_AGG("value" || ' ' || sd."timestamp", ',') as debug
                    FROM
                        sensors_sensordatavalue v
                        INNER JOIN sensors_sensordata sd ON sd.id = sensordata_id
                        INNER JOIN sensors_sensorlocation sl ON sl.id = location_id
                    WHERE
                        v.value_type IN %(filter_value_types)s
                        AND v.value ~ '^\\-?\\d+(\\.?\\d+)?$'
                        """
                           +
                           ("AND sl.city IN %(city_names)s" if len(city_names) > 0 else "")
                           +
                           """
                        AND sd."timestamp" >= %(from_date)s
                        AND sd."timestamp" <= %(to_date)s
                    GROUP BY
                        DATE_TRUNC(%(trunc)s, sd."timestamp"),
                        v.value_type,
                        sl.city
                """, {
                                'filter_value_types': tuple(filter_value_types),
                                'city_names': tuple(city_names),
                                'from_date': from_date,
                                'to_date': to_date,
                                'trunc': avg
                            })
            res = cursor.fetchall()

            print(res)

            return res


class CityView(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = City.objects.all()
    serializer_class = CitySerializer
    pagination_class = StandardResultsSetPagination


class NodesView(viewsets.ViewSet):
    def list(self, request):
        nodes = []
        # Loop through the last active nodes
        for last_active in LastActiveNodes.objects.iterator():
            # Get the current node
            node = Node.objects.filter(
                Q(id=last_active.node.id), ~Q(sensors=None)
            ).get()

            # The last acive date
            last_data_received_at = last_active.last_data_received_at

            # last_data_received_at
            stats = []
            moved_to = None
            # Get data stats from 5mins before last_data_received_at
            if last_data_received_at:
                last_5_mins = last_data_received_at - \
                    datetime.timedelta(minutes=5)
                stats = (
                    SensorDataValue.objects.filter(
                        Q(sensordata__sensor__node=last_active.node.id),
                        Q(sensordata__location=last_active.location.id),
                        Q(sensordata__timestamp__gte=last_5_mins),
                        Q(sensordata__timestamp__lte=last_data_received_at),
                        # Ignore timestamp values
                        ~Q(value_type="timestamp"),
                        # Match only valid float text
                        Q(value__regex=r"^\-?\d+(\.?\d+)?$"),
                    )
                    .order_by()
                    .values("value_type")
                    .annotate(
                        sensor_id=F("sensordata__sensor__id"),
                        start_datetime=Min("sensordata__timestamp"),
                        end_datetime=Max("sensordata__timestamp"),
                        average=Avg(Cast("value", FloatField())),
                        minimum=Min(Cast("value", FloatField())),
                        maximum=Max(Cast("value", FloatField())),
                    )
                )

            # If the last_active node location is not same as current node location
            # then the node has moved locations since it was last active
            if last_active.location.id != node.location.id:
                moved_to = {
                    "name": node.location.location,
                    "longitude": node.location.longitude,
                    "latitude": node.location.latitude,
                    "city": {
                        "name": node.location.city,
                        "slug": slugify(node.location.city),
                    },
                }

            nodes.append(
                {
                    "node_moved": moved_to is not None,
                    "moved_to": moved_to,
                    "node": {
                        "uid": last_active.node.uid,
                        "id": last_active.node.id
                    },
                    "location": {
                        "name": last_active.location.location,
                        "longitude": last_active.location.longitude,
                        "latitude": last_active.location.latitude,
                        "city": {
                            "name": last_active.location.city,
                            "slug": slugify(last_active.location.city),
                        },
                    },
                    "last_data_received_at": last_data_received_at,
                    "stats": stats,
                }
            )
        return Response(nodes)
