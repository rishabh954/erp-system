from __future__ import annotations

from django.contrib.contenttypes.models import ContentType

from apps.notifications.models import (
    EmailLog,
    Notification,
    NotificationPreference,
    SMSLog,
    WhatsAppLog,
)


class NotificationService:
    """Central notification orchestration with tenant-aware preference checks."""

    CHANNELS = {
        "in_app",
        "email",
        "sms",
        "whatsapp",
        "push",
    }

    @staticmethod
    def _normalize_channels(channels):
        if channels is None:
            return ["in_app"]
        if isinstance(channels, str):
            return [channels]
        return list(channels)

    @staticmethod
    def _resolve_company(company=None, recipient=None):
        if company is not None:
            return company
        if recipient is None:
            return None
        for attr in ("primary_company", "company"):
            value = getattr(recipient, attr, None)
            if value is not None:
                return value
        return None

    @classmethod
    def _get_preference(cls, user, notification_type, company=None):
        if not user:
            return None
        resolved_company = cls._resolve_company(company, user)
        if not resolved_company:
            return None
        preference, _ = NotificationPreference.objects.get_or_create(
            user=user,
            company=resolved_company,
            notification_type=notification_type,
            defaults={
                "in_app_enabled": True,
                "email_enabled": True,
                "sms_enabled": False,
                "whatsapp_enabled": False,
                "push_enabled": False,
            },
        )
        return preference

    @classmethod
    def _channel_enabled(cls, recipient, notification_type, channel, company=None):
        if not recipient:
            return True
        if channel not in cls.CHANNELS:
            return True
        preference = cls._get_preference(recipient, notification_type, company)
        if preference is None:
            return True
        return bool(getattr(preference, f"{channel}_enabled", True))

    @classmethod
    def _iter_recipients(cls, recipient):
        if recipient is None:
            return []
        if isinstance(recipient, (list, tuple, set)):
            return list(recipient)
        return [recipient]

    @classmethod
    def send(
        cls,
        recipient,
        title,
        message,
        notification_type="info",
        channels=None,
        action_url="",
        action_label="",
        company=None,
        related_object=None,
        extra_data=None,
    ):
        recipients = cls._iter_recipients(recipient)
        if not recipients:
            return []

        created = []
        for user in recipients:
            resolved_company = cls._resolve_company(company, user)
            if resolved_company is None:
                continue
            for channel in cls._normalize_channels(channels):
                channel_name = str(channel).lower()
                if channel_name not in cls.CHANNELS:
                    continue
                if channel_name != "push" and not cls._channel_enabled(
                    user,
                    notification_type,
                    channel_name,
                    resolved_company,
                ):
                    continue

                if channel_name == "in_app":
                    kwargs = dict(
                        company=resolved_company,
                        recipient=user,
                        notification_type=notification_type,
                        title=title,
                        message=message,
                        action_url=action_url,
                        action_label=action_label,
                    )
                    if extra_data:
                        kwargs["extra_data"] = extra_data
                    if related_object:
                        content_type = ContentType.objects.get_for_model(related_object)
                        kwargs["content_type"] = content_type
                        kwargs["object_id"] = str(related_object.pk)
                    created.append(Notification.objects.create(**kwargs))
                elif channel_name == "email":
                    cls.send_email(
                        user,
                        subject=title,
                        message=message,
                        template="",
                        context={"message": message, "title": title},
                        company=resolved_company,
                        notification_type=notification_type,
                        use_preferences=True,
                    )
                elif channel_name == "sms":
                    cls.send_sms(
                        user,
                        message=message,
                        company=resolved_company,
                        notification_type=notification_type,
                    )
                elif channel_name == "whatsapp":
                    cls.send_whatsapp(
                        user,
                        template_name="notification",
                        template_data={"title": title, "message": message},
                        company=resolved_company,
                        notification_type=notification_type,
                        message=message,
                    )
                elif channel_name == "push":
                    if not cls._channel_enabled(
                        user,
                        notification_type,
                        "push",
                        resolved_company,
                    ):
                        continue
                    created.append(
                        Notification.objects.create(
                            company=resolved_company,
                            recipient=user,
                            notification_type=notification_type,
                            title=title,
                            message=message,
                            action_url=action_url,
                            action_label=action_label,
                            extra_data={"channel": "push", **(extra_data or {})},
                        )
                    )

        return created

    @classmethod
    def send_notification(cls, *args, **kwargs):
        return cls.send(*args, **kwargs)

    @classmethod
    def send_bulk(
        cls,
        recipients,
        title,
        message,
        notification_type="info",
        channels=None,
        action_url="",
        company=None,
        related_object=None,
        extra_data=None,
    ):
        results = []
        for recipient in recipients or []:
            results.extend(
                cls.send(
                    recipient=recipient,
                    title=title,
                    message=message,
                    notification_type=notification_type,
                    channels=channels,
                    action_url=action_url,
                    action_label="",
                    company=company,
                    related_object=related_object,
                    extra_data=extra_data,
                )
            )
        return results

    @classmethod
    def send_bulk_notification(cls, *args, **kwargs):
        return cls.send_bulk(*args, **kwargs)

    @classmethod
    def send_email(
        cls,
        recipient,
        subject,
        message,
        template="",
        context=None,
        company=None,
        notification_type="info",
        recipient_name="",
        use_preferences=True,
    ):
        if not recipient:
            return None

        email_address = (
            recipient
            if isinstance(recipient, str)
            else getattr(recipient, "email", None)
        )
        if not email_address:
            return None

        resolved_company = cls._resolve_company(
            company,
            recipient if not isinstance(recipient, str) else None,
        )
        if resolved_company is None:
            return None
        if use_preferences and not isinstance(recipient, str):
            if not cls._channel_enabled(
                recipient,
                notification_type,
                "email",
                resolved_company,
            ):
                return None

        email_log = EmailLog.objects.create(
            company=resolved_company,
            recipient_email=email_address,
            recipient_name=(
                recipient_name
                or getattr(recipient, "get_full_name", lambda: "")()
                if not isinstance(recipient, str)
                else ""
            ),
            subject=subject,
            body=message,
            status=EmailLog.Status.PENDING,
            template=template,
        )

        from apps.notifications.tasks import send_email_task

        send_email_task.delay(
            to_email=email_address,
            to_name=email_log.recipient_name,
            subject=subject,
            template=template or "generic",
            context=context or {"message": message, "title": subject},
            company_id=str(resolved_company.pk) if resolved_company else None,
        )
        return email_log

    @classmethod
    def send_sms(
        cls,
        recipient,
        message,
        company=None,
        notification_type="info",
    ):
        if not recipient:
            return None
        if hasattr(recipient, "phone_number"):
            phone_number = recipient.phone_number
        elif hasattr(recipient, "mobile_number"):
            phone_number = recipient.mobile_number
        else:
            phone_number = recipient

        resolved_company = cls._resolve_company(
            company,
            recipient if not isinstance(recipient, str) else None,
        )
        if resolved_company is None:
            return None
        if (
            not isinstance(recipient, str)
            and not cls._channel_enabled(
                recipient,
                notification_type,
                "sms",
                resolved_company,
            )
        ):
            return None

        if not phone_number:
            return None

        return SMSLog.objects.create(
            company=resolved_company,
            recipient_phone=str(phone_number),
            recipient_name=(
                getattr(recipient, "get_full_name", lambda: "")()
                if not isinstance(recipient, str)
                else ""
            ),
            message=message,
            status=SMSLog.Status.PENDING,
        )

    @classmethod
    def send_whatsapp(
        cls,
        recipient,
        template_name,
        template_data=None,
        company=None,
        notification_type="info",
        message="",
    ):
        if not recipient:
            return None
        if hasattr(recipient, "phone_number"):
            phone_number = recipient.phone_number
        elif hasattr(recipient, "mobile_number"):
            phone_number = recipient.mobile_number
        else:
            phone_number = recipient

        resolved_company = cls._resolve_company(
            company,
            recipient if not isinstance(recipient, str) else None,
        )
        if resolved_company is None:
            return None
        if (
            not isinstance(recipient, str)
            and not cls._channel_enabled(
                recipient,
                notification_type,
                "whatsapp",
                resolved_company,
            )
        ):
            return None

        if not phone_number:
            return None

        return WhatsAppLog.objects.create(
            company=resolved_company,
            recipient_phone=str(phone_number),
            recipient_name=(
                getattr(recipient, "get_full_name", lambda: "")()
                if not isinstance(recipient, str)
                else ""
            ),
            template_name=template_name,
            template_data=template_data or {},
            message=message,
            status=WhatsAppLog.Status.PENDING,
        )

    @staticmethod
    def mark_read(notification):
        if isinstance(notification, Notification):
            notification.mark_read()
            return notification
        notification_obj = Notification.objects.filter(pk=notification).first()
        if notification_obj:
            notification_obj.mark_read()
        return notification_obj

    @staticmethod
    def mark_all_read(user, company=None):
        if not user:
            return 0
        resolved_company = NotificationService._resolve_company(company, user)
        queryset = Notification.objects.filter(
            recipient=user,
            is_read=False,
        )
        if resolved_company:
            queryset = queryset.filter(company=resolved_company)
        return queryset.update(is_read=True)

    @staticmethod
    def get_unread_count(user, company=None):
        if not user:
            return 0
        resolved_company = NotificationService._resolve_company(company, user)
        queryset = Notification.objects.filter(recipient=user, is_read=False)
        if resolved_company:
            queryset = queryset.filter(company=resolved_company)
        return queryset.count()
