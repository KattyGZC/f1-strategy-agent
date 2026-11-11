"""Replay routes: start and control a replay over REST, watch it over SSE (ADR 0009)."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field

from f1_strategy.adapters.http.responses import (
    CONFLICT,
    NOT_FOUND,
    UNAVAILABLE,
    ErrorResponse,
    Responses,
)
from f1_strategy.adapters.http.services import Services
from f1_strategy.adapters.replay_events import ReplayEvent, ReplayFailedEvent, ReplayResetEvent
from f1_strategy.application.replay import ReplayFailure, ReplayReset, ReplayStatus, StreamEntry
from f1_strategy.domain.playback import Paused, PlaybackStatus, ReplaySpeed

REPLAY_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
STREAM_ID_PATTERN = r"^\d+-\d+$"

router = APIRouter(tags=["replays"])


class StartReplayRequest(BaseModel):
    session_key: int = Field(gt=0)
    speed: ReplaySpeed


class SpeedRequest(BaseModel):
    speed: ReplaySpeed


class SeekRequest(BaseModel):
    lap_number: int = Field(gt=0)


class ReplayResponse(BaseModel):
    replay_id: str
    session_key: int
    status: PlaybackStatus
    speed: ReplaySpeed
    session_s: float = Field(description="Seconds since the session's first event, now")
    failure: str | None


ReplayId = Annotated[str, Path(pattern=REPLAY_ID_PATTERN)]
# An error before the stream starts is JSON; FastAPI would file a response model under the
# route's media type, so the schema is referenced instead.
STREAM_NOT_FOUND: Responses = {
    status.HTTP_404_NOT_FOUND: {
        "description": "Not Found",
        "content": {
            "application/json": {
                "schema": {"$ref": f"#/components/schemas/{ErrorResponse.__name__}"}
            }
        },
    }
}


@router.post(
    "/replays",
    status_code=status.HTTP_201_CREATED,
    responses={**NOT_FOUND, **UNAVAILABLE},
)
async def start_replay(body: StartReplayRequest, services: Services) -> ReplayResponse:
    replay_id = await services.start(body.session_key, body.speed)
    return _response(replay_id, await services.control.status(replay_id))


@router.get("/replays/{replay_id}", responses=NOT_FOUND)
async def read_replay(replay_id: ReplayId, services: Services) -> ReplayResponse:
    return _response(replay_id, await services.control.status(replay_id))


@router.post("/replays/{replay_id}/pause", responses=NOT_FOUND)
async def pause_replay(replay_id: ReplayId, services: Services) -> ReplayResponse:
    return _response(replay_id, await services.control.pause(replay_id))


@router.post("/replays/{replay_id}/resume", responses=NOT_FOUND)
async def resume_replay(replay_id: ReplayId, services: Services) -> ReplayResponse:
    return _response(replay_id, await services.control.resume(replay_id))


@router.put("/replays/{replay_id}/speed", responses=NOT_FOUND)
async def set_replay_speed(
    replay_id: ReplayId, body: SpeedRequest, services: Services
) -> ReplayResponse:
    return _response(replay_id, await services.control.set_speed(replay_id, body.speed))


@router.post("/replays/{replay_id}/seek", responses={**NOT_FOUND, **CONFLICT})
async def seek_replay(replay_id: ReplayId, body: SeekRequest, services: Services) -> ReplayResponse:
    """Moves the replay to the earliest start of the lap among its drivers, keeping its status
    and speed; the event stream sends `replay_reset`, then the session from its start up to
    there. 404 when the replay is gone or no driver has a start for the lap, 409 when the
    replay failed."""
    return _response(replay_id, await services.seek(replay_id, body.lap_number))


@router.delete("/replays/{replay_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
async def stop_replay(replay_id: ReplayId, services: Services) -> None:
    """Removes the replay and frees its place; its event stream ends."""
    await services.control.stop(replay_id)


async def _watched(
    replay_id: ReplayId,
    services: Services,
    last_event_id: Annotated[
        str | None, Header(alias="Last-Event-ID", pattern=STREAM_ID_PATTERN)
    ] = None,
) -> AsyncIterator[StreamEntry | ReplayReset | ReplayFailure]:
    # A dependency, so an unknown replay is a 404 before the stream starts.
    return await services.watch(replay_id, last_event_id)


@router.get(
    "/replays/{replay_id}/events", response_class=EventSourceResponse, responses=STREAM_NOT_FOUND
)
async def watch_replay(
    entries: Annotated[AsyncIterator[StreamEntry | ReplayReset | ReplayFailure], Depends(_watched)],
) -> AsyncIterator[ReplayEvent | ReplayResetEvent | ReplayFailedEvent | ServerSentEvent]:
    """The replay's events from the start, or after `Last-Event-ID`, as they fall due. Each
    event's SSE `event` is its `kind`. A seek sends `replay_reset`, after which the events
    rebuild the session from its start; the stream ends with `replay_failed` if the replay
    fails, and when the replay expires."""
    # The models in the annotation are what `data` holds; they put the event schemas in the
    # OpenAPI document, which a ServerSentEvent alone would leave out.
    async for entry in entries:
        if isinstance(entry, ReplayFailure):
            failed = ReplayFailedEvent(message=entry.message)
            yield ServerSentEvent(raw_data=failed.model_dump_json(), event=failed.kind)
            return
        if isinstance(entry, ReplayReset):
            reset = ReplayResetEvent(lap_number=entry.lap_number, session_s=entry.session_s)
            yield ServerSentEvent(
                raw_data=reset.model_dump_json(), id=entry.entry_id, event=reset.kind
            )
            continue
        yield ServerSentEvent(raw_data=entry.data, id=entry.entry_id, event=entry.kind)


def _response(replay_id: str, replay: ReplayStatus) -> ReplayResponse:
    playback = replay.state.playback
    return ReplayResponse(
        replay_id=replay_id,
        session_key=replay.state.session_key,
        status=PlaybackStatus.PAUSED if isinstance(playback, Paused) else PlaybackStatus.PLAYING,
        speed=playback.speed,
        session_s=replay.session_s,
        failure=replay.state.failure,
    )
