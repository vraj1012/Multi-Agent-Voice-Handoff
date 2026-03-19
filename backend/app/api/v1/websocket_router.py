"""WebSocket Router — Real-time bidirectional voice streaming with barge-in."""
import json
import asyncio
import logging
import traceback
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.voice.stream_manager import StreamManager

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/ws/voice")
async def websocket_voice_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connected.")

    try:
        stream_manager = StreamManager()
    except Exception as e:
        logger.error(f"StreamManager init failed: {e}")
        await websocket.close()
        return

    audio_queue = asyncio.Queue()
    shutdown = asyncio.Event()

    async def receive_loop():
        """Receive audio from client. Barge-in checks run immediately (not queued)."""
        try:
            while not shutdown.is_set():
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break

                if "bytes" in message:
                    audio_data = message["bytes"]

                    # Server-side barge-in check during playback
                    if stream_manager.is_audio_playing_on_client:
                        if stream_manager.check_barge_in_vad(audio_data):
                            try:
                                await websocket.send_text(json.dumps({"type": "status", "content": "interrupted"}))
                            except Exception:
                                pass

                    await audio_queue.put(audio_data)

                elif "text" in message:
                    try:
                        parsed = json.loads(message["text"])
                        if parsed.get("type") == "barge_in":
                            stream_manager.cancel_current_response()
                    except json.JSONDecodeError:
                        pass

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.debug(f"Receive loop ended: {e}")
        finally:
            shutdown.set()
            await audio_queue.put(None)

    async def process_loop():
        """Process queued audio chunks and send responses back."""
        try:
            while not shutdown.is_set():
                chunk = await audio_queue.get()
                if chunk is None:
                    break

                async for response in stream_manager.process_chunk(chunk):
                    if stream_manager.is_cancelled() and response.get("type") == "audio":
                        continue

                    try:
                        if response.get("type") == "audio":
                            await websocket.send_bytes(response["content"])
                        else:
                            await websocket.send_text(json.dumps(response))
                    except Exception:
                        break

                # After a completed turn, drain stale audio that buffered during response
                if stream_manager._turn_just_completed:
                    stream_manager._turn_just_completed = False
                    drained = 0
                    while not audio_queue.empty():
                        try:
                            audio_queue.get_nowait()
                            drained += 1
                        except asyncio.QueueEmpty:
                            break
                    if drained:
                        logger.debug(f"Drained {drained} stale audio chunks after turn")

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"Process loop error: {e}\n{traceback.format_exc()}")
        finally:
            shutdown.set()

    try:
        receive_task = asyncio.create_task(receive_loop())
        process_task = asyncio.create_task(process_loop())

        done, pending = await asyncio.wait(
            [receive_task, process_task], return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}\n{traceback.format_exc()}")
    finally:
        try:
            filepath = stream_manager.save_recording()
            if filepath:
                logger.info(f"Recording saved: {filepath}")
        except Exception as e:
            logger.error(f"Failed to save recording: {e}")

        logger.info("WebSocket disconnected.")
        try:
            await websocket.close()
        except:
            pass
