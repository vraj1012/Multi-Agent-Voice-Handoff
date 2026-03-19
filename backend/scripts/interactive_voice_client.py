
import asyncio
import websockets
import json
import sounddevice as sd
import numpy as np
import queue
import sys
import threading

# Audio Configuration
SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = 'int16'
CHUNK_SIZE = 512  # 32ms window

# Queues for audio data
input_queue = asyncio.Queue()
output_queue = queue.Queue()

# Playback state
is_playing = threading.Event()
# Signal to abort current playback immediately
abort_playback = threading.Event()
# Tracks if playback thread is actively writing audio
playback_busy = threading.Event()

def input_callback(indata, frames, time, status):
    """Callback for input stream."""
    if status:
        print(status, file=sys.stderr)
    
    # Simple VU Meter
    try:
        data_np = np.frombuffer(indata, dtype=np.int16)
        rms = np.sqrt(np.mean(data_np.astype(np.float32)**2))
        bars = int(rms / 300)
        print(f"\r🎤 Volume: {'|' * bars:<20} ({int(rms)})", end="", file=sys.stderr, flush=True)
    except Exception:
        pass
        
    loop.call_soon_threadsafe(input_queue.put_nowait, bytes(indata))

async def send_audio(websocket):
    """Read from mic and send to websocket."""
    print("🎤 Listening... (Speak now)")
    try:
        while True:
            data = await input_queue.get()
            if data:
                await websocket.send(data)
    except asyncio.CancelledError:
        pass

async def receive_messages(websocket):
    """Receive messages from websocket and play audio."""
    print("🎧 Ready to receive audio...")
    try:
        async for message in websocket:
            if isinstance(message, bytes):
                # Binary audio data — mark as playing, skip if playback was aborted
                if not abort_playback.is_set():
                    is_playing.set()
                    output_queue.put(message)
            else:
                try:
                    msg = json.loads(message)
                    if msg.get("type") == "text":
                        print(f"\n🤖 {msg.get('agent', 'Agent')}: {msg.get('content')}")
                        if msg.get("handoff"):
                            print(f"🔀 Handoff to {msg.get('handoff_target', 'unknown')}")
                    elif msg.get("type") == "status":
                        status = msg.get('content')
                        if status == "call_ended":
                            print(f"\n👋 Call ended — waiting for farewell to finish...")
                            # Wait for ALL farewell audio to finish playing
                            # Check both: queue not empty OR playback thread still writing
                            while not output_queue.empty() or playback_busy.is_set():
                                await asyncio.sleep(0.1)
                            # Extra buffer for hardware audio stream to flush
                            await asyncio.sleep(1.5)
                            print("👋 Goodbye!")
                            is_playing.clear()
                            output_queue.put(None)
                            return
                        elif status == "interrupted":
                            # Server barge-in — STOP audio IMMEDIATELY
                            print(f"\n⚡ Barge-in — stopping playback instantly")
                            abort_playback.set()   # Signal playback thread to stop
                            is_playing.clear()
                            # Drain the queue
                            while not output_queue.empty():
                                try:
                                    output_queue.get_nowait()
                                except queue.Empty:
                                    break
                        elif status == "listening":
                            is_playing.clear()
                            abort_playback.clear()  # Reset for next response
                        elif status == "processing":
                            abort_playback.clear()  # Reset for new response
                            print(f"\nℹ️ Status: {status}")
                        else:
                            print(f"\nℹ️ Status: {status}")
                    elif msg.get("type") == "metadata":
                        pass
                    elif msg.get("type") == "transcript" and msg.get("role") == "user":
                        print(f"\n👤 You: {msg.get('content')}")
                except json.JSONDecodeError:
                    print(f"\nReceived unknown message: {message}")
    except websockets.exceptions.ConnectionClosed:
        print("\nConnection closed.")

def playback_thread(output_device=None, enable_preroll=False):
    """Thread to play audio from output queue. Supports instant abort.
    
    When enable_preroll=True (TV/HDMI/BT mode), uses a callback-based stream 
    that continuously feeds silence when idle — keeping the TV audio pipeline 
    permanently active so no audio gets clipped at the start of each message.
    
    When enable_preroll=False (normal mode), uses the original blocking writes
    with zero added latency.
    """
    import collections
    
    if enable_preroll:
        _playback_thread_callback_mode(output_device)
    else:
        _playback_thread_blocking_mode(output_device)


def _playback_thread_callback_mode(output_device=None):
    """Callback-based playback: continuously feeds audio/silence to keep TV/HDMI alive."""
    import collections
    
    # Thread-safe audio ring buffer
    audio_buffer = collections.deque()
    buffer_lock = threading.Lock()
    
    def output_callback(outdata, frames, time_info, status):
        """Called by OS audio driver continuously. Feeds audio or silence."""
        bytes_needed = frames * 2  # 16-bit mono = 2 bytes per sample
        result = bytearray(bytes_needed)
        offset = 0
        
        with buffer_lock:
            while offset < bytes_needed and audio_buffer:
                chunk = audio_buffer[0]
                available = len(chunk)
                needed = bytes_needed - offset
                
                if available <= needed:
                    result[offset:offset + available] = chunk
                    offset += available
                    audio_buffer.popleft()
                else:
                    result[offset:offset + needed] = chunk[:needed]
                    audio_buffer[0] = chunk[needed:]
                    offset = bytes_needed
        
        # Any remaining bytes stay as 0x00 (silence) — keeps HDMI alive
        outdata[:] = bytes(result)
    
    try:
        stream = sd.RawOutputStream(
            samplerate=24000, blocksize=480, dtype=DTYPE, 
            channels=CHANNELS, device=output_device,
            callback=output_callback
        )
        stream.start()
        
        while True:
            data = output_queue.get()
            if data is None:
                break
            
            if abort_playback.is_set():
                # Clear buffer on abort
                with buffer_lock:
                    audio_buffer.clear()
                continue
            
            # Feed audio into ring buffer
            playback_busy.set()
            with buffer_lock:
                audio_buffer.append(data)
            
            # Wait for this chunk to drain from buffer
            while True:
                with buffer_lock:
                    if not audio_buffer:
                        break
                if abort_playback.is_set():
                    with buffer_lock:
                        audio_buffer.clear()
                    break
                threading.Event().wait(0.01)  # 10ms poll
            
            playback_busy.clear()
        
        stream.stop()
        stream.close()
    except Exception as e:
        print(f"\n⚠️ Playback thread ended: {e}", file=sys.stderr)


def _playback_thread_blocking_mode(output_device=None):
    """Original blocking-write playback: zero latency for normal speakers."""
    try:
        stream = sd.RawOutputStream(samplerate=24000, blocksize=CHUNK_SIZE, dtype=DTYPE, channels=CHANNELS, device=output_device)
        stream.start()
        
        # Sub-chunk size: 480 samples * 2 bytes = 960 bytes = 20ms at 24kHz
        SUB_CHUNK_BYTES = 480 * 2
        
        is_first_chunk = True
        
        while True:
            data = output_queue.get()
            if data is None:
                break
            
            if abort_playback.is_set():
                is_first_chunk = True
                continue
                
            if is_first_chunk:
                # Feed 250ms of silence as a jitter buffer to absorb network/generation stutter
                try:
                    stream.write(b'\x00' * int(24000 * 2 * 0.25))
                except Exception:
                    pass
                is_first_chunk = False

            
            # Break large audio chunks into tiny sub-chunks (~20ms each)
            # Check abort between each for instant stop
            playback_busy.set()
            offset = 0
            while offset < len(data):
                if abort_playback.is_set():
                    try:
                        stream.abort()
                        stream.start()
                    except Exception:
                        pass
                    break
                
                end = min(offset + SUB_CHUNK_BYTES, len(data))
                try:
                    stream.write(data[offset:end])
                except Exception:
                    pass
                offset = end
            playback_busy.clear()
        
        stream.stop()
        stream.close()
    except Exception as e:
        print(f"\n⚠️ Playback thread ended: {e}", file=sys.stderr)

async def main():
    uri = "ws://localhost:8000/api/v1/ws/voice"
    global loop
    loop = asyncio.get_running_loop()

    devices = sd.query_devices()

    # --- Input device selection ---
    print("🎤 Available Input Devices:")
    input_devices = [(i, d) for i, d in enumerate(devices) if d['max_input_channels'] > 0]
    for i, dev in input_devices:
        print(f"  [{i}] {dev['name']}")

    input_device_idx = None
    if len(input_devices) > 1:
        try:
            sel = input("Select input device index (default: system default): ")
            if sel.strip():
                input_device_idx = int(sel)
        except ValueError:
            print("Invalid index, using default.")
    print(f"Using input device: {input_device_idx if input_device_idx is not None else 'Default'}")

    # --- Output device selection ---
    print("\n🔊 Available Output Devices:")
    output_devices = [(i, d) for i, d in enumerate(devices) if d['max_output_channels'] > 0]
    for i, dev in output_devices:
        print(f"  [{i}] {dev['name']}")

    output_device_idx = None
    if len(output_devices) > 1:
        try:
            sel = input("Select output device index (default: system default): ")
            if sel.strip():
                output_device_idx = int(sel)
        except ValueError:
            print("Invalid index, using default.")
    print(f"Using output device: {output_device_idx if output_device_idx is not None else 'Default'}")

    # --- Pre-roll option for TV/HDMI/Bluetooth speakers ---
    enable_preroll = False
    try:
        preroll_sel = input("Enable audio pre-roll for TV/HDMI/Bluetooth speakers? (y/N): ").strip().lower()
        enable_preroll = preroll_sel in ('y', 'yes')
    except (ValueError, EOFError):
        pass
    if enable_preroll:
        print("✅ Pre-roll enabled (250ms silence before each response)")

    print(f"Connecting to {uri}...")
    async with websockets.connect(uri, max_size=10 * 1024 * 1024, open_timeout=60, ping_timeout=60) as websocket:
        print("✅ Connected!")
        print("💡 Barge-in: Speak clearly while the agent is talking to interrupt")
        
        # Start audio input stream
        input_stream = sd.RawInputStream(
            device=input_device_idx,
            samplerate=SAMPLE_RATE,
            blocksize=CHUNK_SIZE,
            dtype=DTYPE,
            channels=CHANNELS,
            callback=input_callback
        )

        # Start playback thread with selected output device
        player = threading.Thread(target=playback_thread, args=(output_device_idx, enable_preroll), daemon=True)
        player.start()
        
        with input_stream:
            sender_task = asyncio.create_task(send_audio(websocket))
            receiver_task = asyncio.create_task(receive_messages(websocket))
            
            done, pending = await asyncio.wait(
                [sender_task, receiver_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            for task in pending:
                task.cancel()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopping...")
        output_queue.put(None)
