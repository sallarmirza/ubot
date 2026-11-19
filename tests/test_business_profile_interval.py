import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import ValidationError

from schema.business_profile_schema import BusinessProfileRequest
from services import business_profile_service


class BusinessProfileIntervalTests(unittest.TestCase):
	def test_profile_request_accepts_valid_intervals_and_legacy_payloads(self):
		for interval in (1, 5, 1440):
			with self.subTest(interval=interval):
				payload = BusinessProfileRequest(
					channel_id="channel",
					comment_fetch_interval_minutes=interval,
				)
				self.assertEqual(
					payload.comment_fetch_interval_minutes, interval
				)

		legacy_payload = BusinessProfileRequest(channel_id="channel")
		self.assertIsNone(legacy_payload.comment_fetch_interval_minutes)

	def test_profile_request_rejects_invalid_intervals(self):
		for interval in (0, 1441, 1.5, True, "5", None):
			with self.subTest(interval=interval):
				with self.assertRaises(ValidationError):
					BusinessProfileRequest(
						channel_id="channel",
						comment_fetch_interval_minutes=interval,
					)

	def test_save_persona_updates_shared_interval_and_returns_it(self):
		db = Mock()
		channel = SimpleNamespace(
			youtube_channel_id="channel", channel_name="Channel"
		)
		target = SimpleNamespace(target_channel_id=9)
		db.query.return_value.filter_by.return_value.first.return_value = None
		payload = BusinessProfileRequest(
			channel_id="channel",
			business_name="Brand",
			comment_fetch_interval_minutes=15,
		)

		with patch.object(
			business_profile_service,
			"_find_user_channel",
			return_value=channel,
		), patch.object(
			business_profile_service,
			"_find_or_create_target",
			return_value=target,
		), patch.object(
			business_profile_service.auth_repository,
			"get_comment_monitoring_settings",
			side_effect=[
				{"enabled": True, "comment_fetch_interval_minutes": 5},
				{"enabled": True, "comment_fetch_interval_minutes": 15},
			],
		), patch.object(
			business_profile_service.auth_repository,
			"set_comment_monitoring_enabled",
		) as set_settings:
			result = business_profile_service.save_business_profile(
				db, 12, payload
			)

		set_settings.assert_called_once_with(db, 12, True, 15)
		db.commit.assert_called_once()
		self.assertEqual(result["comment_fetch_interval_minutes"], 15)

	def test_legacy_persona_save_preserves_current_interval(self):
		db = Mock()
		channel = SimpleNamespace(
			youtube_channel_id="channel", channel_name="Channel"
		)
		target = SimpleNamespace(target_channel_id=9)
		db.query.return_value.filter_by.return_value.first.return_value = None
		payload = BusinessProfileRequest(
			channel_id="channel", business_name="Brand"
		)

		with patch.object(
			business_profile_service,
			"_find_user_channel",
			return_value=channel,
		), patch.object(
			business_profile_service,
			"_find_or_create_target",
			return_value=target,
		), patch.object(
			business_profile_service.auth_repository,
			"get_comment_monitoring_settings",
			return_value={
				"enabled": True,
				"comment_fetch_interval_minutes": 30,
			},
		), patch.object(
			business_profile_service.auth_repository,
			"set_comment_monitoring_enabled",
		) as set_settings:
			result = business_profile_service.save_business_profile(
				db, 12, payload
			)

		set_settings.assert_called_once_with(db, 12, True, None)
		self.assertEqual(result["comment_fetch_interval_minutes"], 30)


if __name__ == "__main__":
	unittest.main()
