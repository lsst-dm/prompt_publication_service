# This file is part of prompt_publication_service.
#
# Developed for the LSST Data Management System.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from asyncio import Lock
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Self

from aiokafka import AIOKafkaConsumer


class KafkaReader(AbstractAsyncContextManager):
    """Wrapper around a Kafka Consumer to read messages sent to a topic by a
    transactional producer, with manual commit of the consumer read offset.
    """

    def __init__(
        self, bootstrap_servers: str, topic: str, group_id: str, username: str, password: str
    ) -> None:
        self._lock = Lock()
        self._pending_message: str | None = None
        self._consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            security_protocol="SASL_PLAINTEXT",
            sasl_mechanism="SCRAM-SHA-512",
            sasl_plain_username=username,
            sasl_plain_password=password,
            # We manually call commit() to ensure at-least-once
            # processing of messages.
            enable_auto_commit=False,
            # Start processing messages from the beginning of the queue.  We
            # will have committed offsets if we have processed some of the
            # messages already, in which case this setting is ignored.
            auto_offset_reset="earliest",
            # Prompt Processing Butler Writer is using transactions.
            isolation_level="read_committed",
        )

    async def __aenter__(self) -> Self:
        await self._consumer.start()
        return self

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        await self._consumer.stop()

    @asynccontextmanager
    async def read_next_message_and_commit_on_success(self) -> AsyncIterator[str]:
        """Context manager that returns the next message from Kafka.  If the
        context manager is exited without an exception, the read position will
        be committed to Kafka.  If an exception occurs in the scope of the
        context manager, the read position will not be committed and the next
        read will return the same message.
        """
        async with self._lock:
            if self._pending_message is None:
                message = await self._consumer.getone()
                self._pending_message = message.value.decode("utf-8")
            else:
                # The caller's processing of the previous message failed.  We
                # return the same message again to ensure at-least-once
                # processing.
                pass

            yield self._pending_message
            await self._consumer.commit()
            self._pending_message = None
