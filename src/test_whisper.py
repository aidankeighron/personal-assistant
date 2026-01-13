"""
Bypass Pipecat's WhisperSTTService and test Whisper directly.
This will confirm if the issue is with Whisper itself or Pipecat's wrapper.
"""
import asyncio
import pyaudio
import numpy as np
from faster_whisper import WhisperModel

# Audio settings
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
RECORD_SECONDS = 5
AUDIO_INDEX = 1

def main():
    print("=" * 50)
    print("DIRECT WHISPER TEST (bypassing Pipecat)")
    print("=" * 50)
    
    # Load Whisper
    print("\nLoading Whisper model...")
    model = WhisperModel("distil-medium.en", device="cpu", compute_type="int8")
    print("Whisper loaded!")
    
    # Setup PyAudio
    p = pyaudio.PyAudio()
    stream = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        input_device_index=AUDIO_INDEX,
        frames_per_buffer=CHUNK
    )
    
    print(f"\nRecording for {RECORD_SECONDS} seconds... SPEAK NOW!")
    print("-" * 50)
    
    # Record audio
    frames = []
    for _ in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
        data = stream.read(CHUNK, exception_on_overflow=False)
        frames.append(data)
    
    print("Recording complete!")
    
    # Stop stream
    stream.stop_stream()
    stream.close()
    p.terminate()
    
    # Convert to numpy array
    audio_data = b''.join(frames)
    audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
    
    print(f"Audio captured: {len(audio_np)} samples ({len(audio_np)/RATE:.2f} seconds)")
    print(f"Audio range: min={audio_np.min():.4f}, max={audio_np.max():.4f}")
    
    # Transcribe
    print("\nTranscribing with Whisper...")
    segments, info = model.transcribe(audio_np, beam_size=5)
    
    print(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")
    print("\n" + "=" * 50)
    print("TRANSCRIPTION:")
    print("=" * 50)
    
    full_text = ""
    for segment in segments:
        print(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")
        full_text += segment.text
    
    if not full_text.strip():
        print("(No speech detected)")
    
    print("=" * 50)

if __name__ == "__main__":
    main()
