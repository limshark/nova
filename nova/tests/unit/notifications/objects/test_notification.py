# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
import collections

import mock
from oslo_utils import timeutils
from oslo_versionedobjects import fixture

from nova import exception
from nova.notifications.objects import base as notification
from nova import objects
from nova.objects import base
from nova.objects import fields
from nova import test
from nova.tests.unit.objects import test_objects
from nova.tests import uuidsentinel as uuids


class TestNotificationBase(test.NoDBTestCase):

    @base.NovaObjectRegistry.register_if(False)
    class TestObject(base.NovaObject):
        VERSION = '1.0'
        fields = {
            'field_1': fields.StringField(),
            'field_2': fields.IntegerField(),
            'not_important_field': fields.IntegerField(),
            'lazy_field': fields.IntegerField()
        }

        def obj_load_attr(self, attrname):
            if attrname == 'lazy_field':
                self.lazy_field = 42
            else:
                raise exception.ObjectActionError(
                    action='obj_load_attr',
                    reason='attribute %s not lazy-loadable' % attrname)

        def __init__(self, not_important_field):
            super(TestNotificationBase.TestObject, self).__init__()
            # field1 and field_2 simulates that some fields are initialized
            # outside of the object's ctor
            self.not_important_field = not_important_field

    @base.NovaObjectRegistry.register_if(False)
    class TestNotificationPayload(notification.NotificationPayloadBase):
        VERSION = '1.0'

        SCHEMA = {
            'field_1': ('source_field', 'field_1'),
            'field_2': ('source_field', 'field_2'),
            'lazy_field': ('source_field', 'lazy_field')
        }

        fields = {
            'extra_field': fields.StringField(),  # filled by ctor
            # filled by the schema
            'field_1': fields.StringField(nullable=True),
            'field_2': fields.IntegerField(),   # filled by the schema
            'lazy_field': fields.IntegerField()  # filled by the schema
        }

        def __init__(self, extra_field, source_field):
            super(TestNotificationBase.TestNotificationPayload,
                  self).__init__()
            self.extra_field = extra_field
            self.populate_schema(source_field=source_field)

    @base.NovaObjectRegistry.register_if(False)
    class TestNotificationPayloadEmptySchema(
        notification.NotificationPayloadBase):
        VERSION = '1.0'

        fields = {
            'extra_field': fields.StringField(),  # filled by ctor
        }

        def __init__(self, extra_field):
            super(TestNotificationBase.TestNotificationPayloadEmptySchema,
                  self).__init__()
            self.extra_field = extra_field

    @notification.notification_sample('test-update-1.json')
    @notification.notification_sample('test-update-2.json')
    @base.NovaObjectRegistry.register_if(False)
    class TestNotification(notification.NotificationBase):
        VERSION = '1.0'
        fields = {
            'payload': fields.ObjectField('TestNotificationPayload')
        }

    @base.NovaObjectRegistry.register_if(False)
    class TestNotificationEmptySchema(notification.NotificationBase):
        VERSION = '1.0'
        fields = {
            'payload': fields.ObjectField('TestNotificationPayloadEmptySchema')
        }

    fake_service = {
        'created_at': timeutils.utcnow().replace(microsecond=0),
        'updated_at': None,
        'deleted_at': None,
        'deleted': False,
        'id': 123,
        'uuid': uuids.service,
        'host': 'fake-host',
        'binary': 'nova-compute',
        'topic': 'fake-service-topic',
        'report_count': 1,
        'forced_down': False,
        'disabled': False,
        'disabled_reason': None,
        'last_seen_up': None,
        'version': 1}

    expected_payload = {
        'nova_object.name': 'TestNotificationPayload',
        'nova_object.data': {
            'extra_field': 'test string',
            'field_1': 'test1',
            'field_2': 15,
            'lazy_field': 42},
        'nova_object.version': '1.0',
        'nova_object.namespace': 'nova'}

    def setUp(self):
        super(TestNotificationBase, self).setUp()
        with mock.patch('nova.db.service_update') as mock_db_service_update:
            self.service_obj = objects.Service(context=mock.sentinel.context,
                                               id=self.fake_service['id'])
            self.service_obj.obj_reset_changes(['version'])
            mock_db_service_update.return_value = self.fake_service
            self.service_obj.save()

        self.my_obj = self.TestObject(not_important_field=13)
        self.my_obj.field_1 = 'test1'
        self.my_obj.field_2 = 15

        self.payload = self.TestNotificationPayload(
            extra_field='test string', source_field=self.my_obj)

        self.notification = self.TestNotification(
            event_type=notification.EventType(
                object='test_object',
                action=fields.NotificationAction.UPDATE,
                phase=fields.NotificationPhase.START),
            publisher=notification.NotificationPublisher.from_service_obj(
                self.service_obj),
            priority=fields.NotificationPriority.INFO,
            payload=self.payload)

    def _verify_notification(self, mock_notifier, mock_context,
                             expected_event_type,
                             expected_payload):
        mock_notifier.prepare.assert_called_once_with(
            publisher_id='nova-compute:fake-host')
        mock_notify = mock_notifier.prepare.return_value.info
        self.assertTrue(mock_notify.called)
        self.assertEqual(mock_notify.call_args[0][0], mock_context)
        self.assertEqual(mock_notify.call_args[1]['event_type'],
                         expected_event_type)
        actual_payload = mock_notify.call_args[1]['payload']
        self.assertJsonEqual(expected_payload, actual_payload)

    @mock.patch('nova.rpc.LEGACY_NOTIFIER')
    @mock.patch('nova.rpc.NOTIFIER')
    def test_emit_notification(self, mock_notifier, mock_legacy):

        mock_context = mock.Mock()
        mock_context.to_dict.return_value = {}
        self.notification.emit(mock_context)

        self._verify_notification(
            mock_notifier,
            mock_context,
            expected_event_type='test_object.update.start',
            expected_payload=self.expected_payload)
        self.assertFalse(mock_legacy.called)

    @mock.patch('nova.rpc.NOTIFIER')
    def test_emit_with_host_and_binary_as_publisher(self, mock_notifier):
        noti = self.TestNotification(
            event_type=notification.EventType(
                object='test_object',
                action=fields.NotificationAction.UPDATE),
            publisher=notification.NotificationPublisher(
                host='fake-host',
                source='nova-compute'),
            priority=fields.NotificationPriority.INFO,
            payload=self.payload)

        mock_context = mock.Mock()
        mock_context.to_dict.return_value = {}
        noti.emit(mock_context)

        self._verify_notification(
            mock_notifier,
            mock_context,
            expected_event_type='test_object.update',
            expected_payload=self.expected_payload)

    @mock.patch('nova.rpc.LEGACY_NOTIFIER')
    @mock.patch('nova.rpc.NOTIFIER')
    def test_emit_event_type_without_phase(self, mock_notifier, mock_legacy):
        noti = self.TestNotification(
            event_type=notification.EventType(
                object='test_object',
                action=fields.NotificationAction.UPDATE),
            publisher=notification.NotificationPublisher.from_service_obj(
                self.service_obj),
            priority=fields.NotificationPriority.INFO,
            payload=self.payload)

        mock_context = mock.Mock()
        mock_context.to_dict.return_value = {}
        noti.emit(mock_context)

        self._verify_notification(
            mock_notifier,
            mock_context,
            expected_event_type='test_object.update',
            expected_payload=self.expected_payload)
        self.assertFalse(mock_legacy.called)

    @mock.patch('nova.rpc.NOTIFIER')
    def test_not_possible_to_emit_if_not_populated(self, mock_notifier):
        payload = self.TestNotificationPayload(
            extra_field='test string', source_field=self.my_obj)
        payload.populated = False

        noti = self.TestNotification(
            event_type=notification.EventType(
                object='test_object',
                action=fields.NotificationAction.UPDATE),
            publisher=notification.NotificationPublisher.from_service_obj(
                self.service_obj),
            priority=fields.NotificationPriority.INFO,
            payload=payload)

        mock_context = mock.Mock()
        self.assertRaises(AssertionError, noti.emit, mock_context)
        self.assertFalse(mock_notifier.called)

    def test_lazy_load_source_field(self):
        my_obj = self.TestObject(not_important_field=13)
        my_obj.field_1 = 'test1'
        my_obj.field_2 = 15

        payload = self.TestNotificationPayload(extra_field='test string',
                                               source_field=my_obj)

        self.assertEqual(42, payload.lazy_field)

    def test_uninited_source_field_defaulted_to_none(self):
        my_obj = self.TestObject(not_important_field=13)
        # intentionally not initializing field_1 to simulate an uninited but
        # nullable field
        my_obj.field_2 = 15

        payload = self.TestNotificationPayload(extra_field='test string',
                                               source_field=my_obj)

        self.assertIsNone(payload.field_1)

    def test_uninited_source_field_not_nullable_payload_field_fails(self):
        my_obj = self.TestObject(not_important_field=13)
        # intentionally not initializing field_2 to simulate an uninited no
        # nullable field
        my_obj.field_1 = 'test1'

        self.assertRaises(ValueError, self.TestNotificationPayload,
                          extra_field='test string', source_field=my_obj)

    @mock.patch('nova.rpc.NOTIFIER')
    def test_empty_schema(self, mock_notifier):
        non_populated_payload = self.TestNotificationPayloadEmptySchema(
            extra_field='test string')
        noti = self.TestNotificationEmptySchema(
            event_type=notification.EventType(
                object='test_object',
                action=fields.NotificationAction.UPDATE),
            publisher=notification.NotificationPublisher.from_service_obj(
                self.service_obj),
            priority=fields.NotificationPriority.INFO,
            payload=non_populated_payload)

        mock_context = mock.Mock()
        mock_context.to_dict.return_value = {}
        noti.emit(mock_context)

        self._verify_notification(
            mock_notifier,
            mock_context,
            expected_event_type='test_object.update',
            expected_payload=
            {'nova_object.name': 'TestNotificationPayloadEmptySchema',
             'nova_object.data': {'extra_field': u'test string'},
             'nova_object.version': '1.0',
             'nova_object.namespace': 'nova'})

    def test_sample_decorator(self):
        self.assertEqual(2, len(self.TestNotification.samples))
        self.assertIn('test-update-1.json', self.TestNotification.samples)
        self.assertIn('test-update-2.json', self.TestNotification.samples)

    @mock.patch('nova.notifications.objects.base.NotificationBase._emit')
    @mock.patch('nova.rpc.NOTIFIER')
    def test_payload_is_not_generated_if_notifier_is_not_enabled(
            self, mock_notifier, mock_emit):
        mock_notifier.is_enabled.return_value = False

        payload = self.TestNotificationPayload(
            extra_field='test string',
            source_field=self.my_obj)
        noti = self.TestNotification(
            event_type=notification.EventType(
                object='test_object',
                action=fields.NotificationAction.UPDATE),
            publisher=notification.NotificationPublisher.from_service_obj(
                self.service_obj),
            priority=fields.NotificationPriority.INFO,
            payload=payload)

        mock_context = mock.Mock()

        noti.emit(mock_context)

        self.assertFalse(payload.populated)
        self.assertFalse(mock_emit.called)

    @mock.patch('nova.notifications.objects.base.NotificationBase._emit')
    def test_payload_is_not_generated_if_notification_format_is_unversioned(
            self, mock_emit):
        self.flags(notification_format='unversioned', group='notifications')

        payload = self.TestNotificationPayload(
            extra_field='test string',
            source_field=self.my_obj)
        noti = self.TestNotification(
            event_type=notification.EventType(
                object='test_object',
                action=fields.NotificationAction.UPDATE),
            publisher=notification.NotificationPublisher.from_service_obj(
                self.service_obj),
            priority=fields.NotificationPriority.INFO,
            payload=payload)

        mock_context = mock.Mock()

        noti.emit(mock_context)

        self.assertFalse(payload.populated)
        self.assertFalse(mock_emit.called)

notification_object_data = {
    'AggregateNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'AggregatePayload': '1.1-1eb9adcc4440d8627de6ec37c6398746',
    'AuditPeriodPayload': '1.0-2b429dd307b8374636703b843fa3f9cb',
    'BandwidthPayload': '1.0-ee2616a7690ab78406842a2b68e34130',
    'BlockDevicePayload': '1.0-29751e1b6d41b1454e36768a1e764df8',
    'EventType': '1.10-2a6ab743d767837366ab1aec387d7c3b',
    'ExceptionNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'ExceptionPayload': '1.1-6c43008bd81885a63bc7f7c629f0793b',
    'FlavorNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'FlavorPayload': '1.4-2e7011b8b4e59167fe8b7a0a81f0d452',
    'InstanceActionNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceActionPayload': '1.6-e9e4cbb94e07d3bcaa22743f41e094c8',
    'InstanceActionRebuildNotification':
        '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceActionRebuildPayload': '1.7-db0d6d549a7932428cdc0c7ca78859b5',
    'InstanceActionRescueNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceActionRescuePayload': '1.1-99b9b25574b77abf6d3e5a0cea341b06',
    'InstanceActionResizePrepNotification':
        '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceActionResizePrepPayload': '1.1-9dd5cd4124c660a86e3f00a2df222b8e',
    'InstanceActionVolumeNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceActionVolumePayload': '1.4-83fcb4c12327da998116844ef4a16235',
    'InstanceActionVolumeSwapNotification':
    '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceActionVolumeSwapPayload': '1.6-bb322fd649d3626c7a83d5f2d9a866d4',
    'InstanceCreateNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceCreatePayload': '1.9-1c9f722bf51ddae910fb7e50fff8edd1',
    'InstancePayload': '1.6-b1e7818c7adf158e8a6e87e0944b0b21',
    'InstanceActionSnapshotNotification':
        '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceActionSnapshotPayload': '1.7-73f96d93ca47750bb6a45e4ab1d268fd',
    'InstanceExistsNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceExistsPayload': '1.0-9b0c1232136e6c850647dfabb63cff07',
    'InstanceStateUpdatePayload': '1.0-07e111c0fa0f6db0f79b0726d593e3da',
    'InstanceUpdateNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'InstanceUpdatePayload': '1.7-d48dd2cf8310c8f250dfeb65fd9df97a',
    'IpPayload': '1.0-8ecf567a99e516d4af094439a7632d34',
    'KeypairNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'KeypairPayload': '1.0-6daebbbde0e1bf35c1556b1ecd9385c1',
    'NotificationPublisher': '2.2-b6ad48126247e10b46b6b0240e52e614',
    'ServerGroupNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'ServerGroupPayload': '1.0-eb4bd1738b4670cfe1b7c30344c143c3',
    'ServiceStatusNotification': '1.0-a73147b93b520ff0061865849d3dfa56',
    'ServiceStatusPayload': '1.1-7b6856bd879db7f3ecbcd0ca9f35f92f',
}


class TestNotificationObjectVersions(test.NoDBTestCase):
    def setUp(self):
        super(TestNotificationObjectVersions, self).setUp()
        base.NovaObjectRegistry.register_notification_objects()

    def test_versions(self):
        checker = fixture.ObjectVersionChecker(
            test_objects.get_nova_objects())
        notification_object_data.update(test_objects.object_data)
        expected, actual = checker.test_hashes(notification_object_data,
                                               extra_data_func=get_extra_data)
        self.assertEqual(expected, actual,
                         'Some notification objects have changed; please make '
                         'sure the versions have been bumped, and then update '
                         'their hashes here.')

    def test_notification_payload_version_depends_on_the_schema(self):
        @base.NovaObjectRegistry.register_if(False)
        class TestNotificationPayload(notification.NotificationPayloadBase):
            VERSION = '1.0'

            SCHEMA = {
                'field_1': ('source_field', 'field_1'),
                'field_2': ('source_field', 'field_2'),
            }

            fields = {
                'extra_field': fields.StringField(),  # filled by ctor
                'field_1': fields.StringField(),  # filled by the schema
                'field_2': fields.IntegerField(),   # filled by the schema
            }

        checker = fixture.ObjectVersionChecker(
            {'TestNotificationPayload': (TestNotificationPayload,)})

        old_hash = checker.get_hashes(extra_data_func=get_extra_data)
        TestNotificationPayload.SCHEMA['field_3'] = ('source_field',
                                                     'field_3')
        new_hash = checker.get_hashes(extra_data_func=get_extra_data)

        self.assertNotEqual(old_hash, new_hash)


def get_extra_data(obj_class):
    extra_data = tuple()

    # Get the SCHEMA items to add to the fingerprint
    # if we are looking at a notification
    if issubclass(obj_class, notification.NotificationPayloadBase):
        schema_data = collections.OrderedDict(
            sorted(obj_class.SCHEMA.items()))

        extra_data += (schema_data,)

    return extra_data
