"""LinkedIn data adapter utilities."""





























































from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import aiohttp


def _load_li_safety():
    ""






    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import li_safety  # noqa: E402  (intentional late import next to this file)

    return li_safety


from cpc.exceptions import (
    ChannelAuthError,
    ChannelNotFoundError,
    ChannelRateLimitError,
    ChannelTransientError,
)
from cpc.models.canonical import (
    Attachment,
    ChannelAccount,
    ChannelType,
    ConnectionStatus,
    Direction,
    IdentifierType,
    Identity,
    LinkedInMetadata,
    SyncCursor,
    UnifiedContact,
    UnifiedMessage,
    UnifiedThread,
)
from cpc.ports import (
    CommunicationPort,
    ConnectionPort,
    ContactPort,
    MessageQuery,
    PagedResult,
    SendPort,
)

logger = logging.getLogger(__name__)

LI_API_BASE = "https://www.linkedin.com/voyager/api"
LI_GRAPHQL_BASE = f"{LI_API_BASE}/voyagerMessagingGraphQL/graphql"


QUERY_IDS = {
    "conversations": "messengerConversations.0d5e6781bbee71c3e51c8843c6519f48",
    "messages": "messengerMessages.5846eeb71c981f11e0134cb6626cc314",
    "conversations_paginated": "messengerConversations.9501074288a12f3ae9e3c7ea243bccbf",
    "profile_by_vanity": "voyagerIdentityDashProfiles.a1a483e719b20537a256b6853cdca711",
}


def encode_restli(value: str) -> str:
    ""
    return (
        value.replace(":", "%3A")
        .replace("(", "%28")
        .replace(")", "%29")
        .replace(",", "%2C")
        .replace("=", "%3D")
    )


class LinkedInAdapter(CommunicationPort, SendPort, ContactPort, ConnectionPort):
    ""





    def __init__(self):
        self._account: ChannelAccount | None = None
        self._session: aiohttp.ClientSession | None = None
        self._li_at: str | None = None
        self._jsessionid: str | None = None
        self._csrf_token: str | None = None
        self._user_urn: str | None = None
        self._last_poll_time: float = 0


        self._safety = None
        self._guard = None

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.LINKEDIN



    async def initialize(self, account: ChannelAccount) -> None:
        ""









        self._account = account




        try:
            self._safety = _load_li_safety()
        except Exception as e:
            raise ChannelAuthError(
                "LinkedIn adapter refuses to start: shared safety module "
                f"(li_safety.py) could not be imported: {e}. "
                "Wire li_safety before enabling this adapter.",
                channel=ChannelType.LINKEDIN,
                account_id=account.id,
                original_error=e,
            )


        self._guard = self._safety.LinkedInSafetyGuard()



        self._csrf_token = (self._jsessionid or "").strip('"') if self._jsessionid else ""

        headers = {
            "csrf-token": self._csrf_token,
            "x-li-lang": "en_US",
            "x-li-track": json.dumps(
                {
                    "clientVersion": "1.13.20589",
                    "mpVersion": "1.13.20589",
                    "osName": "web",
                    "timezoneOffset": 1,
                    "deviceFormFactor": "DESKTOP",
                    "mpName": "voyager-web",
                }
            ),
            "x-restli-protocol-version": "2.0.0",
            "x-li-page-instance": "urn:li:page:messaging_thread;",
        }

        cookie_jar = aiohttp.CookieJar()
        self._session = aiohttp.ClientSession(
            headers=headers,
            cookie_jar=cookie_jar,
            timeout=aiohttp.ClientTimeout(total=30),
        )


        if self._li_at:
            self._session.cookie_jar.update_cookies(
                {"li_at": self._li_at, "JSESSIONID": self._jsessionid or ""},
                response_url=aiohttp.client.URL("https://www.linkedin.com"),
            )


        try:
            profile = await self._get_own_profile()
            logger.info(f"LinkedIn adapter initialized for URN: {self._user_urn}")
        except Exception as e:
            raise ChannelAuthError(
                f"LinkedIn authentication failed: {e}",
                channel=ChannelType.LINKEDIN,
                account_id=account.id,
                original_error=e,
            )

    async def shutdown(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None



    def _require_guard(self):
        ""





        if self._guard is None or self._safety is None:
            raise ChannelAuthError(
                "LinkedIn safety guard not initialized; refusing outbound call. "
                "Call initialize() first (it wires li_safety).",
                channel=ChannelType.LINKEDIN,
            )
        return self._guard

    async def _safe_request(
        self, method: str, url: str, *, params=None, json_data=None, accept_headers=None
    ) -> dict:
        ""














        guard = self._require_guard()
        safety = self._safety
        accept_headers = accept_headers or {
            "Accept": "application/vnd.linkedin.normalized+json+2.1"
        }



        guard.check_killswitch()

        while True:

            try:
                guard.assert_under_caps()
            except safety.CapExceeded as e:
                raise ChannelRateLimitError(
                    f"LinkedIn cap reached: {e}",
                    channel=ChannelType.LINKEDIN,
                    retry_after_seconds=300.0,
                )


            await asyncio.to_thread(guard.wait)

            try:
                async with self._session.request(
                    method,
                    url,
                    params=params,
                    json=json_data,
                    headers=accept_headers,
                ) as resp:
                    status = resp.status
                    final_url = str(resp.url)
                    body_text = await resp.text()
            except (TimeoutError, aiohttp.ClientError):

                status, body_text, final_url = None, "", url


            verdict = guard.classify_response(status, body_text, final_url)

            if verdict == safety.TRANSIENT:
                try:
                    await asyncio.to_thread(guard.transient_backoff)
                except safety.TransientAbort as e:
                    raise ChannelTransientError(
                        f"LinkedIn transient backoff exhausted: {e}",
                        channel=ChannelType.LINKEDIN,
                    )
                continue

            if verdict == safety.GONE:
                raise ChannelNotFoundError(
                    f"LinkedIn resource not found/bad ({status}): {body_text[:200]}",
                    channel=ChannelType.LINKEDIN,
                )


            guard.reset_transient_backoff()
            guard.record_call()
            try:
                return json.loads(body_text) if body_text else {}
            except json.JSONDecodeError:


                raise ChannelTransientError(
                    "LinkedIn returned non-JSON body on a data endpoint",
                    channel=ChannelType.LINKEDIN,
                )

    async def _graphql_get(self, query_id: str, variables: dict[str, Any]) -> dict:
        ""
        params = {
            "queryId": query_id,
            "variables": json.dumps(variables),
        }
        return await self._safe_request("GET", LI_GRAPHQL_BASE, params=params)

    async def _api_get(self, path: str, params: dict | None = None) -> dict:
        ""
        return await self._safe_request("GET", f"{LI_API_BASE}{path}", params=params)

    async def _api_post(self, path: str, data: dict) -> dict:
        ""
        return await self._safe_request(
            "POST",
            f"{LI_API_BASE}{path}",
            json_data=data,
            accept_headers={
                "Accept": "application/vnd.linkedin.normalized+json+2.1",
                "Content-Type": "application/json",
            },
        )

    async def _handle_li_error(self, resp: aiohttp.ClientResponse) -> None:
        ""







        if resp.status == 200:
            return

        body = await resp.text()

        if resp.status in (401, 403):
            raise ChannelAuthError(
                f"LinkedIn API auth error ({resp.status}): {body[:200]}",
                channel=ChannelType.LINKEDIN,
            )
        elif resp.status == 429:
            raise ChannelRateLimitError(
                "LinkedIn API rate limited",
                channel=ChannelType.LINKEDIN,
                retry_after_seconds=300.0,
            )
        elif resp.status >= 500:
            raise ChannelTransientError(
                f"LinkedIn API server error {resp.status}",
                channel=ChannelType.LINKEDIN,
            )
        elif resp.status == 404:
            raise ChannelNotFoundError(
                f"LinkedIn resource not found: {body[:200]}",
                channel=ChannelType.LINKEDIN,
            )
        else:
            raise ChannelTransientError(
                f"LinkedIn API error {resp.status}: {body[:200]}",
                channel=ChannelType.LINKEDIN,
            )

    async def _get_own_profile(self) -> dict:
        ""
        return await self._api_get("/identity/profiles/me")







    def _transform_message(
        self,
        raw: dict,
        *,
        conversation_urn: str | None = None,
        included_map: dict[str, dict] | None = None,
    ) -> UnifiedMessage:
        ""



























        included_map = included_map or {}


        message_urn = raw.get("entityUrn", raw.get("backendUrn", ""))


        timestamp_ms = raw.get("createdAt", 0)


        sender_data = self._extract_sender(raw, included_map)
        sender_urn = sender_data.get("urn", "")
        sender = Identity(
            type=IdentifierType.LINKEDIN_URN,
            value=sender_urn,
        )


        is_outbound = sender_urn == self._user_urn
        direction = Direction.OUTBOUND if is_outbound else Direction.INBOUND


        body_text = self._extract_body(raw)


        attachments = self._extract_li_attachments(raw)


        recipient_urns = self._extract_recipients(raw, included_map, conversation_urn)

        recipients = [
            Identity(type=IdentifierType.LINKEDIN_URN, value=urn)
            for urn in recipient_urns
            if urn != sender_urn
        ]


        metadata = LinkedInMetadata(
            conversation_urn=conversation_urn,
            message_urn=message_urn,
            sender_urn=sender_urn,
            recipient_urns=recipient_urns,
            is_connection_request=raw.get("subtype") == "INVITATION",
            connection_note=(body_text if raw.get("subtype") == "INVITATION" else None),
            is_inmail=raw.get("subtype") == "INMAIL",
        )

        return UnifiedMessage(
            id=f"linkedin:{message_urn}",
            channel=ChannelType.LINKEDIN,
            account_id=self._account.id if self._account else "",
            direction=direction,
            timestamp=timestamp_ms,
            sender=sender,
            recipients=recipients,
            subject=None,
            body_text=body_text,
            thread_id=f"linkedin:{conversation_urn}" if conversation_urn else None,
            attachments=attachments,
            channel_metadata=metadata,
        )

    def _extract_sender(self, raw: dict, included_map: dict) -> dict:
        ""
        from_data = raw.get("from", {})


        if "com.linkedin.voyager.messaging.MessagingMember" in from_data:
            member = from_data["com.linkedin.voyager.messaging.MessagingMember"]
            mini_profile = member.get("miniProfile", {})
            return {
                "urn": mini_profile.get("entityUrn", ""),
                "first_name": mini_profile.get("firstName", ""),
                "last_name": mini_profile.get("lastName", ""),
                "vanity": mini_profile.get("publicIdentifier", ""),
            }


        if isinstance(from_data, dict) and "_type" in from_data:
            return {
                "urn": from_data.get("entityUrn", ""),
                "first_name": from_data.get("firstName", ""),
                "last_name": from_data.get("lastName", ""),
            }


        from_urn = raw.get("from", "")
        if isinstance(from_urn, str) and from_urn in included_map:
            member = included_map[from_urn]
            return {
                "urn": member.get("entityUrn", from_urn),
                "first_name": member.get("firstName", ""),
                "last_name": member.get("lastName", ""),
            }

        return {"urn": str(from_data), "first_name": "", "last_name": ""}

    def _extract_body(self, raw: dict) -> str:
        ""
        event_content = raw.get("eventContent", {})


        msg_event_key = "com.linkedin.voyager.messaging.event.MessageEvent"
        if msg_event_key in event_content:
            return event_content[msg_event_key].get("body", "")


        if "body" in event_content:
            return event_content["body"]


        return raw.get("body", "")

    def _extract_li_attachments(self, raw: dict) -> list[Attachment]:
        ""
        attachments = []
        event_content = raw.get("eventContent", {})

        msg_event_key = "com.linkedin.voyager.messaging.event.MessageEvent"
        msg_event = event_content.get(msg_event_key, event_content)

        for att in msg_event.get("attachments", []):
            attachments.append(
                Attachment(
                    filename=att.get("name", "attachment"),
                    mime_type=att.get("mediaType", "application/octet-stream"),
                    size_bytes=att.get("byteSize"),
                    url=att.get("reference", {}).get("string"),
                )
            )

        return attachments

    def _extract_recipients(
        self, raw: dict, included_map: dict, conversation_urn: str | None
    ) -> list[str]:
        ""

        if conversation_urn and conversation_urn in included_map:
            conv = included_map[conversation_urn]
            participants = conv.get("participants", [])
            return [p.get("entityUrn", "") if isinstance(p, dict) else str(p) for p in participants]
        return []

    def _transform_conversation(self, raw: dict, included_map: dict | None = None) -> UnifiedThread:
        ""
        included_map = included_map or {}
        conv_urn = raw.get("entityUrn", "")


        participants = []
        for p in raw.get("participants", []):
            if isinstance(p, dict):
                mini = p.get(
                    "miniProfile", p.get("com.linkedin.voyager.messaging.MessagingMember", {})
                )
                urn = mini.get("entityUrn", p.get("entityUrn", ""))
            else:
                urn = str(p)
            if urn:
                participants.append(Identity(type=IdentifierType.LINKEDIN_URN, value=urn))

        return UnifiedThread(
            id=f"linkedin:{conv_urn}",
            channel=ChannelType.LINKEDIN,
            account_id=self._account.id if self._account else "",
            participants=participants,
            message_count=raw.get("totalEventCount", 0),
            last_activity=(
                datetime.fromtimestamp(raw.get("lastActivityAt", 0) / 1000, tz=UTC)
                if raw.get("lastActivityAt")
                else None
            ),
            channel_metadata=LinkedInMetadata(conversation_urn=conv_urn),
            is_group=len(participants) > 2,
        )



    async def list_messages(self, query: MessageQuery | None = None) -> PagedResult[UnifiedMessage]:
        ""
        limit = query.limit if query else 20


        variables = {"count": min(limit, 40)}
        response = await self._graphql_get(QUERY_IDS["conversations"], variables)


        included = response.get("included", [])
        included_map = {item.get("entityUrn", item.get("$id", "")): item for item in included}


        messages: list[UnifiedMessage] = []
        for item in included:
            item_type = item.get("$type", item.get("_type", ""))
            if "Event" in item_type or "message" in item_type.lower():
                try:
                    msg = self._transform_message(item, included_map=included_map)
                    messages.append(msg)
                except Exception as e:
                    logger.warning(f"Failed to transform LinkedIn message: {e}")


        messages.sort(key=lambda m: m.timestamp, reverse=True)

        return PagedResult(items=messages[:limit])

    async def get_message(self, message_id: str) -> UnifiedMessage | None:
        ""

        logger.warning("LinkedIn: get_message by ID requires conversation context")
        return None

    async def search(self, query_text: str, *, limit: int = 20) -> list[UnifiedMessage]:
        ""



        logger.info(f"LinkedIn search is client-side only. Query: {query_text}")

        return []

    async def get_thread(
        self, thread_id: str, *, load_messages: bool = True
    ) -> UnifiedThread | None:
        ""
        conv_urn = thread_id.removeprefix("linkedin:")

        if not load_messages:

            variables = {"conversationUrn": conv_urn}
            response = await self._graphql_get(QUERY_IDS["conversations"], variables)
            included = response.get("included", [])
            for item in included:
                if item.get("entityUrn") == conv_urn:
                    return self._transform_conversation(item)
            return None


        variables = {
            "conversationUrn": conv_urn,
            "count": 100,
        }
        response = await self._graphql_get(QUERY_IDS["messages"], variables)
        included = response.get("included", [])
        included_map = {item.get("entityUrn", item.get("$id", "")): item for item in included}

        messages = []
        conv_data = None
        for item in included:
            item_type = item.get("$type", item.get("_type", ""))
            if "Event" in item_type:
                try:
                    msg = self._transform_message(
                        item, conversation_urn=conv_urn, included_map=included_map
                    )
                    messages.append(msg)
                except Exception as e:
                    logger.warning(f"Failed to transform message: {e}")
            elif item.get("entityUrn") == conv_urn:
                conv_data = item

        messages.sort(key=lambda m: m.timestamp)

        if conv_data:
            thread = self._transform_conversation(conv_data, included_map)
            thread.messages = messages
            thread.message_count = len(messages)
            return thread


        participants = list({m.sender for m in messages})
        return UnifiedThread(
            id=thread_id,
            channel=ChannelType.LINKEDIN,
            account_id=self._account.id if self._account else "",
            participants=participants,
            message_count=len(messages),
            last_activity=messages[-1].timestamp if messages else None,
            messages=messages,
        )

    async def list_threads(
        self, *, limit: int = 50, cursor: str | None = None
    ) -> PagedResult[UnifiedThread]:
        ""
        variables: dict[str, Any] = {"count": min(limit, 40)}
        if cursor:
            variables["createdBefore"] = int(cursor)

        response = await self._graphql_get(QUERY_IDS["conversations_paginated"], variables)

        included = response.get("included", [])
        included_map = {item.get("entityUrn", item.get("$id", "")): item for item in included}

        threads = []
        for item in included:
            item_type = item.get("$type", item.get("_type", ""))
            if "Conversation" in item_type:
                try:
                    thread = self._transform_conversation(item, included_map)
                    threads.append(thread)
                except Exception as e:
                    logger.warning(f"Failed to transform conversation: {e}")

        threads.sort(
            key=lambda t: t.last_activity or datetime.min.replace(tzinfo=UTC), reverse=True
        )


        next_cursor = None
        if threads and len(threads) >= limit:
            last_thread = threads[-1]
            if last_thread.last_activity:
                next_cursor = str(int(last_thread.last_activity.timestamp() * 1000))

        return PagedResult(
            items=threads,
            next_cursor=next_cursor,
            has_more=next_cursor is not None,
        )

    async def sync_historical(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        cursor: SyncCursor | None = None,
        progress_callback: Any | None = None,
    ) -> AsyncIterator[UnifiedMessage]:
        ""








        page_cursor = cursor.cursor_value if cursor else None
        total_synced = 0

        while True:

            threads_page = await self.list_threads(limit=20, cursor=page_cursor)

            for thread in threads_page.items:

                if since and thread.last_activity and thread.last_activity < since:
                    return
                if until and thread.last_activity and thread.last_activity > until:
                    continue


                full_thread = await self.get_thread(thread.id, load_messages=True)
                if full_thread:
                    for msg in full_thread.messages:
                        if since and msg.timestamp < since:
                            continue
                        if until and msg.timestamp > until:
                            continue
                        yield msg
                        total_synced += 1

                if progress_callback:
                    await progress_callback(total_synced, None)






            if not threads_page.has_more:
                break
            page_cursor = threads_page.next_cursor

    async def watch_new(self) -> AsyncIterator[UnifiedMessage]:
        ""















        poll_interval = 300
        last_seen_timestamp = int(time.time() * 1000)

        while True:


            if self._guard is not None:
                self._guard.check_killswitch()
            try:
                threads = await self.list_threads(limit=10)

                for thread in threads.items:
                    if thread.last_activity:
                        thread_ts = int(thread.last_activity.timestamp() * 1000)
                        if thread_ts > last_seen_timestamp:

                            full_thread = await self.get_thread(thread.id, load_messages=True)
                            if full_thread:
                                for msg in full_thread.messages:
                                    msg_ts = int(msg.timestamp.timestamp() * 1000)
                                    if msg_ts > last_seen_timestamp:
                                        yield msg

                last_seen_timestamp = int(time.time() * 1000)

            except ChannelRateLimitError:
                logger.warning("LinkedIn rate limited during watch, backing off")
                await asyncio.sleep(300)
            except Exception as e:
                logger.error(f"LinkedIn watch error: {e}")
                await asyncio.sleep(poll_interval * 2)

            await asyncio.sleep(poll_interval)

    async def get_sync_cursor(self) -> SyncCursor | None:
        if not self._account:
            return None
        return SyncCursor(
            account_id=self._account.id,
            channel=ChannelType.LINKEDIN,
            cursor_value=str(int(time.time() * 1000)),
            cursor_type="created_before_ms",
        )



    async def create_draft(self, **kwargs) -> UnifiedMessage:
        ""
        raise NotImplementedError(
            "LinkedIn does not support drafts. "
            "Use send_message() directly or store the draft locally."
        )

    async def send_message(
        self,
        *,
        recipients: list[str],
        subject: str | None = None,
        body_text: str,
        body_html: str | None = None,
        attachments: list[Attachment] | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> UnifiedMessage:
        ""





        recipient_urns = [
            f"urn:li:fsd_profile:{r}" if not r.startswith("urn:") else r for r in recipients
        ]

        payload = {
            "keyVersion": "LEGACY_INBOX",
            "conversationCreate": {
                "eventCreate": {
                    "value": {
                        "com.linkedin.voyager.messaging.create.MessageCreate": {
                            "body": body_text,
                            "attachments": [],
                        }
                    }
                },
                "recipients": recipient_urns,
                "subtype": "MEMBER_TO_MEMBER",
            },
        }

        response = await self._api_post("/messaging/conversations", data=payload)


        return UnifiedMessage(
            id=f"linkedin:sent:{int(time.time() * 1000)}",
            channel=ChannelType.LINKEDIN,
            account_id=self._account.id if self._account else "",
            direction=Direction.OUTBOUND,
            timestamp=datetime.now(UTC),
            sender=Identity(
                type=IdentifierType.LINKEDIN_URN,
                value=self._user_urn or "",
            ),
            recipients=[
                Identity(type=IdentifierType.LINKEDIN_URN, value=urn) for urn in recipient_urns
            ],
            body_text=body_text,
            channel_metadata=LinkedInMetadata(
                recipient_urns=recipient_urns,
                sender_urn=self._user_urn,
            ),
        )

    async def reply_to(
        self,
        *,
        thread_id: str,
        in_reply_to_id: str | None = None,
        body_text: str,
        body_html: str | None = None,
        attachments: list[Attachment] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UnifiedMessage:
        ""
        conv_urn = thread_id.removeprefix("linkedin:")
        encoded_urn = encode_restli(conv_urn)

        payload = {
            "eventCreate": {
                "value": {
                    "com.linkedin.voyager.messaging.create.MessageCreate": {
                        "body": body_text,
                        "attachments": [],
                    }
                }
            }
        }

        response = await self._api_post(
            f"/messaging/conversations/{encoded_urn}/events",
            data=payload,
        )

        return UnifiedMessage(
            id=f"linkedin:reply:{int(time.time() * 1000)}",
            channel=ChannelType.LINKEDIN,
            account_id=self._account.id if self._account else "",
            direction=Direction.OUTBOUND,
            timestamp=datetime.now(UTC),
            sender=Identity(
                type=IdentifierType.LINKEDIN_URN,
                value=self._user_urn or "",
            ),
            body_text=body_text,
            thread_id=thread_id,
            channel_metadata=LinkedInMetadata(
                conversation_urn=conv_urn,
                sender_urn=self._user_urn,
            ),
        )

    async def forward(
        self,
        *,
        message_id: str,
        to_recipients: list[str],
        body_text: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UnifiedMessage:
        ""
        forward_text = body_text or ""
        return await self.send_message(
            recipients=to_recipients,
            body_text=forward_text,
        )



    async def get_contacts(
        self, *, limit: int = 100, cursor: str | None = None
    ) -> PagedResult[UnifiedContact]:
        ""




        params: dict[str, Any] = {
            "count": min(limit, 100),
            "start": int(cursor) if cursor else 0,
            "sortType": "RECENTLY_ADDED",
        }

        response = await self._api_get("/relationships/connections", params=params)

        contacts = []
        for conn in response.get("included", []):
            if conn.get("$type", "").endswith("MiniProfile") or "firstName" in conn:
                contact = self._transform_li_contact(conn)
                if contact:
                    contacts.append(contact)

        start = int(cursor) if cursor else 0
        next_start = start + len(contacts)

        return PagedResult(
            items=contacts,
            total=response.get("paging", {}).get("total"),
            next_cursor=str(next_start) if len(contacts) >= limit else None,
            has_more=len(contacts) >= limit,
        )

    async def resolve_identity(
        self, identifier: str, identifier_type: str | None = None
    ) -> UnifiedContact | None:
        ""
        if identifier_type == "linkedin_vanity" or "/" in identifier:

            vanity = identifier.split("/")[-1]
            variables = {"vanityName": vanity}
            try:
                response = await self._graphql_get(QUERY_IDS["profile_by_vanity"], variables)
                for item in response.get("included", []):
                    if "firstName" in item:
                        return self._transform_li_contact(item)
            except Exception as e:
                logger.warning(f"Failed to resolve LinkedIn profile '{identifier}': {e}")
        return None

    async def get_profile(self, contact_id: str) -> UnifiedContact | None:
        ""
        return await self.resolve_identity(contact_id, "linkedin_vanity")

    def _transform_li_contact(self, raw: dict) -> UnifiedContact | None:
        ""
        first_name = raw.get("firstName", "")
        last_name = raw.get("lastName", "")
        if not first_name and not last_name:
            return None

        display_name = f"{first_name} {last_name}".strip()
        urn = raw.get("entityUrn", "")

        identifiers = []
        if urn:
            identifiers.append(
                Identity(
                    type=IdentifierType.LINKEDIN_URN,
                    value=urn,
                    primary=True,
                )
            )

        vanity = raw.get("publicIdentifier")
        if vanity:
            identifiers.append(
                Identity(
                    type=IdentifierType.LINKEDIN_VANITY,
                    value=vanity,
                )
            )


        avatar_url = None
        picture = raw.get("picture", {})
        if isinstance(picture, dict):
            artifacts = picture.get("artifacts", picture.get("rootUrl"))
            if isinstance(artifacts, list) and artifacts:
                root = picture.get("rootUrl", "")
                artifact = artifacts[-1]
                file_segment = artifact.get("fileIdentifyingUrlPathSegment", "")
                if root and file_segment:
                    avatar_url = f"{root}{file_segment}"


        occupation = raw.get("occupation", "")
        headline = raw.get("headline", "")

        return UnifiedContact(
            id=f"linkedin:{urn}",
            display_name=display_name,
            first_name=first_name,
            last_name=last_name,
            identifiers=identifiers,
            company=None,
            title=occupation or headline or None,
            avatar_url=avatar_url,
            source_channel=ChannelType.LINKEDIN,
        )



    async def add_account(self, account: ChannelAccount) -> ChannelAccount:
        await self.initialize(account)
        account.connection_status = ConnectionStatus.ACTIVE
        return account

    async def remove_account(self, account_id: str) -> bool:
        await self.shutdown()
        return True

    async def get_status(self) -> ConnectionStatus:
        try:
            await self._get_own_profile()
            return ConnectionStatus.ACTIVE
        except ChannelAuthError:
            return ConnectionStatus.AUTH_EXPIRED
        except ChannelRateLimitError:
            return ConnectionStatus.RATE_LIMITED
        except Exception:
            return ConnectionStatus.ERROR

    async def test_connection(self) -> dict[str, Any]:
        start = time.monotonic()
        try:
            profile = await self._get_own_profile()
            latency = (time.monotonic() - start) * 1000
            return {
                "connected": True,
                "latency_ms": round(latency, 1),
                "user_urn": self._user_urn,
            }
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            return {
                "connected": False,
                "latency_ms": round(latency, 1),
                "error": str(e),
            }

    async def refresh_credentials(self) -> bool:
        ""
        logger.warning(
            "LinkedIn credentials (cookies) cannot be refreshed programmatically. "
            "User must re-authenticate in the browser."
        )
        return False
