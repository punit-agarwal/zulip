# -*- coding: utf-8 -*-

import json
import mock
from typing import Any, Union, Mapping, Callable

from zerver.lib.actions import (
    do_create_user,
    get_service_bot_events,
)
from zerver.lib.bot_lib import StateHandler, StateHandlerError
from zerver.lib.test_classes import ZulipTestCase
from zerver.models import (
    get_realm,
    BotUserStateData,
    UserProfile,
    Recipient,
)

BOT_TYPE_TO_QUEUE_NAME = {
    UserProfile.OUTGOING_WEBHOOK_BOT: 'outgoing_webhooks',
    UserProfile.EMBEDDED_BOT: 'embedded_bots',
}

class TestServiceBotBasics(ZulipTestCase):
    def _get_outgoing_bot(self):
        # type: () -> UserProfile
        outgoing_bot = do_create_user(
            email="bar-bot@zulip.com",
            password="test",
            realm=get_realm("zulip"),
            full_name="BarBot",
            short_name='bb',
            bot_type=UserProfile.OUTGOING_WEBHOOK_BOT,
            bot_owner=self.example_user('cordelia'),
        )

        return outgoing_bot

    def test_service_events_for_pms(self):
        # type: () -> None
        sender = self.example_user('hamlet')
        assert(not sender.is_bot)

        outgoing_bot = self._get_outgoing_bot()

        event_dict = get_service_bot_events(
            sender=sender,
            service_bot_tuples=[
                (outgoing_bot.id, outgoing_bot.bot_type),
            ],
            active_user_ids={outgoing_bot.id},
            mentioned_user_ids=set(),
            recipient_type=Recipient.PERSONAL,
        )

        expected = dict(
            outgoing_webhooks=[
                dict(trigger='private_message', user_profile_id=outgoing_bot.id),
            ],
        )

        self.assertEqual(event_dict, expected)

    def test_service_events_for_stream_mentions(self):
        # type: () -> None
        sender = self.example_user('hamlet')
        assert(not sender.is_bot)

        outgoing_bot = self._get_outgoing_bot()

        event_dict = get_service_bot_events(
            sender=sender,
            service_bot_tuples=[
                (outgoing_bot.id, outgoing_bot.bot_type),
            ],
            active_user_ids=set(),
            mentioned_user_ids={outgoing_bot.id},
            recipient_type=Recipient.STREAM,
        )

        expected = dict(
            outgoing_webhooks=[
                dict(trigger='mention', user_profile_id=outgoing_bot.id),
            ],
        )

        self.assertEqual(event_dict, expected)

class TestServiceBotStateHandler(ZulipTestCase):
    def setUp(self):
        # type: () -> None
        self.user_profile = self.example_user("othello")
        self.bot_profile = do_create_user(email="embedded-bot-1@zulip.com",
                                          password="test",
                                          realm=get_realm("zulip"),
                                          full_name="EmbeddedBo1",
                                          short_name="embedded-bot-1",
                                          bot_type=UserProfile.EMBEDDED_BOT,
                                          bot_owner=self.user_profile)
        self.second_bot_profile = do_create_user(email="embedded-bot-2@zulip.com",
                                                 password="test",
                                                 realm=get_realm("zulip"),
                                                 full_name="EmbeddedBot2",
                                                 short_name="embedded-bot-2",
                                                 bot_type=UserProfile.EMBEDDED_BOT,
                                                 bot_owner=self.user_profile)

    def test_basic_storage_and_retrieval(self):
        # type: () -> None
        storage = StateHandler(self.bot_profile)
        storage.put('some key', 'some value')
        storage.put('some other key', 'some other value')
        self.assertEqual(storage.get('some key'), 'some value')
        self.assertEqual(storage.get('some other key'), 'some other value')
        self.assertTrue(storage.contains('some key'))
        self.assertFalse(storage.contains('nonexistent key'))
        self.assertRaises(BotUserStateData.DoesNotExist, lambda: storage.get('nonexistent key'))
        storage.put('some key', 'a new value')
        self.assertEqual(storage.get('some key'), 'a new value')

        second_storage = StateHandler(self.second_bot_profile)
        self.assertRaises(BotUserStateData.DoesNotExist, lambda: second_storage.get('some key'))
        second_storage.put('some key', 'yet another value')
        self.assertEqual(storage.get('some key'), 'a new value')
        self.assertEqual(second_storage.get('some key'), 'yet another value')

    def test_marshaling(self):
        # type: () -> None
        storage = StateHandler(self.bot_profile)
        serializable_obj = {'foo': 'bar', 'baz': [42, 'cux']}
        storage.put('some key', serializable_obj)  # type: ignore # Ignore for testing.
        self.assertEqual(storage.get('some key'), serializable_obj)

    def test_invalid_calls(self):
        # type: () -> None
        storage = StateHandler(self.bot_profile)
        storage.marshal = lambda obj: obj
        storage.demarshal = lambda obj: obj
        serializable_obj = {'foo': 'bar', 'baz': [42, 'cux']}
        with self.assertRaisesMessage(StateHandlerError, "Cannot set state. The value type is "
                                                         "<class 'dict'>, but it should be str."):
            storage.put('some key', serializable_obj)  # type: ignore # We intend to test an invalid type.
        with self.assertRaisesMessage(StateHandlerError, "Cannot set state. The key type is "
                                                         "<class 'dict'>, but it should be str."):
            storage.put(serializable_obj, 'some value')  # type: ignore # We intend to test an invalid type.

    def test_storage_limit(self):
        # type: () -> None
        # Reduce maximal state size for faster test string construction.
        StateHandler.state_size_limit = 100
        storage = StateHandler(self.bot_profile)
        key = 'capacity-filling entry'
        storage.put(key, 'x' * (StateHandler.state_size_limit - len(key)))

        with self.assertRaisesMessage(StateHandlerError, "Cannot set state. Request would require 134 bytes storage. "
                                                         "The current storage limit is 100."):
            storage.put('too much data', 'a few bits too long')

        second_storage = StateHandler(self.second_bot_profile)
        second_storage.put('another big entry', 'x' * (StateHandler.state_size_limit - 40))
        second_storage.put('normal entry', 'abcd')

    def test_entry_removal(self):
        # type: () -> None
        storage = StateHandler(self.bot_profile)
        storage.put('some key', 'some value')
        storage.put('another key', 'some value')
        self.assertTrue(storage.contains('some key'))
        self.assertTrue(storage.contains('another key'))
        storage.remove('some key')
        self.assertFalse(storage.contains('some key'))
        self.assertTrue(storage.contains('another key'))
        self.assertRaises(BotUserStateData.DoesNotExist, lambda: storage.remove('some key'))

class TestServiceBotEventTriggers(ZulipTestCase):

    def setUp(self):
        # type: () -> None
        self.user_profile = self.example_user("othello")
        self.bot_profile = do_create_user(email="foo-bot@zulip.com",
                                          password="test",
                                          realm=get_realm("zulip"),
                                          full_name="FooBot",
                                          short_name="foo-bot",
                                          bot_type=UserProfile.OUTGOING_WEBHOOK_BOT,
                                          bot_owner=self.user_profile)
        self.second_bot_profile = do_create_user(email="bar-bot@zulip.com",
                                                 password="test",
                                                 realm=get_realm("zulip"),
                                                 full_name="BarBot",
                                                 short_name="bar-bot",
                                                 bot_type=UserProfile.OUTGOING_WEBHOOK_BOT,
                                                 bot_owner=self.user_profile)

    @mock.patch('zerver.lib.actions.queue_json_publish')
    def test_trigger_on_stream_mention_from_user(self, mock_queue_json_publish):
        # type: (mock.Mock) -> None
        for bot_type, expected_queue_name in BOT_TYPE_TO_QUEUE_NAME.items():
            self.bot_profile.bot_type = bot_type
            self.bot_profile.save()

            content = u'@**FooBot** foo bar!!!'
            recipient = 'Denmark'
            trigger = 'mention'
            message_type = Recipient._type_names[Recipient.STREAM]

            def check_values_passed(queue_name, trigger_event, x, call_consume_in_tests):
                # type: (Any, Union[Mapping[Any, Any], Any], Callable[[Any], None], bool) -> None
                self.assertEqual(queue_name, expected_queue_name)
                self.assertEqual(trigger_event["message"]["content"], content)
                self.assertEqual(trigger_event["message"]["display_recipient"], recipient)
                self.assertEqual(trigger_event["message"]["sender_email"], self.user_profile.email)
                self.assertEqual(trigger_event["message"]["type"], message_type)
                self.assertEqual(trigger_event['trigger'], trigger)
                self.assertEqual(trigger_event['user_profile_id'], self.bot_profile.id)
            mock_queue_json_publish.side_effect = check_values_passed

            self.send_stream_message(
                self.user_profile.email,
                'Denmark',
                content)
            self.assertTrue(mock_queue_json_publish.called)

    @mock.patch('zerver.lib.actions.queue_json_publish')
    def test_no_trigger_on_stream_message_without_mention(self, mock_queue_json_publish):
        # type: (mock.Mock) -> None
        sender_email = self.user_profile.email
        self.send_stream_message(sender_email, "Denmark")
        self.assertFalse(mock_queue_json_publish.called)

    @mock.patch('zerver.lib.actions.queue_json_publish')
    def test_no_trigger_on_stream_mention_from_bot(self, mock_queue_json_publish):
        # type: (mock.Mock) -> None
        for bot_type in BOT_TYPE_TO_QUEUE_NAME:
            self.bot_profile.bot_type = bot_type
            self.bot_profile.save()

            self.send_stream_message(
                self.second_bot_profile.email,
                'Denmark',
                u'@**FooBot** foo bar!!!')
            self.assertFalse(mock_queue_json_publish.called)

    @mock.patch('zerver.lib.actions.queue_json_publish')
    def test_trigger_on_personal_message_from_user(self, mock_queue_json_publish):
        # type: (mock.Mock) -> None
        for bot_type, expected_queue_name in BOT_TYPE_TO_QUEUE_NAME.items():
            self.bot_profile.bot_type = bot_type
            self.bot_profile.save()

            sender_email = self.user_profile.email
            recipient_email = self.bot_profile.email

            def check_values_passed(queue_name, trigger_event, x, call_consume_in_tests):
                # type: (Any, Union[Mapping[Any, Any], Any], Callable[[Any], None], bool) -> None
                self.assertEqual(queue_name, expected_queue_name)
                self.assertEqual(trigger_event["user_profile_id"], self.bot_profile.id)
                self.assertEqual(trigger_event["trigger"], "private_message")
                self.assertEqual(trigger_event["message"]["sender_email"], sender_email)
                display_recipients = [
                    trigger_event["message"]["display_recipient"][0]["email"],
                    trigger_event["message"]["display_recipient"][1]["email"],
                ]
                self.assertTrue(sender_email in display_recipients)
                self.assertTrue(recipient_email in display_recipients)
            mock_queue_json_publish.side_effect = check_values_passed

            self.send_personal_message(sender_email, recipient_email, 'test')
            self.assertTrue(mock_queue_json_publish.called)

    @mock.patch('zerver.lib.actions.queue_json_publish')
    def test_no_trigger_on_personal_message_from_bot(self, mock_queue_json_publish):
        # type: (mock.Mock) -> None
        for bot_type in BOT_TYPE_TO_QUEUE_NAME:
            self.bot_profile.bot_type = bot_type
            self.bot_profile.save()

            sender_email = self.second_bot_profile.email
            recipient_email = self.bot_profile.email
            self.send_personal_message(sender_email, recipient_email)
            self.assertFalse(mock_queue_json_publish.called)

    @mock.patch('zerver.lib.actions.queue_json_publish')
    def test_trigger_on_huddle_message_from_user(self, mock_queue_json_publish):
        # type: (mock.Mock) -> None
        for bot_type, expected_queue_name in BOT_TYPE_TO_QUEUE_NAME.items():
            self.bot_profile.bot_type = bot_type
            self.bot_profile.save()

            self.second_bot_profile.bot_type = bot_type
            self.second_bot_profile.save()

            sender_email = self.user_profile.email
            recipient_emails = [self.bot_profile.email, self.second_bot_profile.email]
            profile_ids = [self.bot_profile.id, self.second_bot_profile.id]

            def check_values_passed(queue_name, trigger_event, x, call_consume_in_tests):
                # type: (Any, Union[Mapping[Any, Any], Any], Callable[[Any], None], bool) -> None
                self.assertEqual(queue_name, expected_queue_name)
                self.assertIn(trigger_event["user_profile_id"], profile_ids)
                profile_ids.remove(trigger_event["user_profile_id"])
                self.assertEqual(trigger_event["trigger"], "private_message")
                self.assertEqual(trigger_event["message"]["sender_email"], sender_email)
                self.assertEqual(trigger_event["message"]["type"], u'private')
            mock_queue_json_publish.side_effect = check_values_passed

            self.send_huddle_message(sender_email, recipient_emails, 'test')
            self.assertEqual(mock_queue_json_publish.call_count, 2)
            mock_queue_json_publish.reset_mock()

    @mock.patch('zerver.lib.actions.queue_json_publish')
    def test_no_trigger_on_huddle_message_from_bot(self, mock_queue_json_publish):
        # type: (mock.Mock) -> None
        for bot_type in BOT_TYPE_TO_QUEUE_NAME:
            self.bot_profile.bot_type = bot_type
            self.bot_profile.save()

            sender_email = self.second_bot_profile.email
            recipient_emails = [self.user_profile.email, self.bot_profile.email]
            self.send_huddle_message(sender_email, recipient_emails)
            self.assertFalse(mock_queue_json_publish.called)
